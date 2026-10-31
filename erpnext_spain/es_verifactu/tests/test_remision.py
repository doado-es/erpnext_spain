# Tests de REMISIÓN VeriFactu — lote 5a (spec 04 §8): el OUTBOX DRIVER
# (VerifactuDriver) + el drenaje REAL vía AEATOutboxManager con el cliente
# AEAT mockeado (grabar/reproducir de aeat/tests/mock_aeat_client.py).
#
# Cubre: outbox (get_companies/get_pending ordenado y con límite de lote,
# SIN gate de «activada»), la forma wire EXACTA del payload (Cabecera +
# RegistroFactura anidado por tipo con IDFactura/RefExterna/Encadenamiento
# por espejo de la referencia), el drenaje completo (transiciones del libro
# por la VÍA SANCIONADA del flag + denormalización de facturas con el mapper
# de emission.py + persistencia de ES AEAT Response y sus líneas), las
# líneas de ANULACIÓN, las líneas sintéticas de SOAP Fault (Incorrecto con
# codigo_error), el aislamiento de errores permanentes por empresa y la
# entrada cron del planificador. La estrategia de subsanación es lote 5b.
#
# Misma NOTA de colocación que test_emision_registros.py: módulo en tests/,
# sin IGNORE_TEST_RECORD_DEPENDENCIES (raise NotImplementedError fuera de
# carpeta de doctype). Masters reales del site; rollback POR CLASE (el
# setUp devuelve la compañía a estado prístino y borra sus registros del
# libro por db.delete). El rate-limit del manager vive en Redis (estado de
# control efímero, no de negocio): el setUp limpia la clave para que cada
# drain arranque habilitado aunque el test anterior marcó un envío.

from __future__ import annotations

import glob
import json
import os
import unittest.mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate
from zeep.exceptions import Fault

from erpnext_spain.aeat.client import _fault_to_synthetic_response
from erpnext_spain.aeat.manager import AEATOutboxManager
from erpnext_spain.aeat.tests.helpers import (
	clean_pem,
	generate_p12,
	test_company,
	write_private_p12,
)
from erpnext_spain.aeat.tests.mock_aeat_client import MockAEATClient, load_seed
from erpnext_spain.aeat.utils import absolute_site_path, format_aeat_date
from erpnext_spain.es_verifactu import emission
from erpnext_spain.es_verifactu.doctype.es_verifactu_billing_record.es_verifactu_billing_record import (
	RESPONSE_PROCESSOR_FLAG,
)
from erpnext_spain.es_verifactu.driver import VerifactuDriver
from erpnext_spain.tests.fixtures import TEST_CUSTOMER, TEST_ITEM

P12_PATTERN = "es_test_remision_*.p12"
PASSWORD = "es-test-pass"

VALID_NIF = "12345678Z"
ACTIVATION_DATE = "2026-01-01"

DRAFT_SERIES = "BORRADOR-.#####"
F1_SERIES = "SIF1-.####."
F2_SERIES = "SIF2-.####."
R1_SERIES = "RC-.####."

CUSTOMER = TEST_CUSTOMER
ITEM = TEST_ITEM

LEDGER_DOCTYPE = "ES Verifactu Billing Record"
RESPONSE_DOCTYPE = "ES AEAT Response"

OPERATION = "RegFactuSistemaFacturacion"


def _delete_test_p12() -> None:
	for path in glob.glob(absolute_site_path("private", "files", P12_PATTERN)):
		os.remove(path)


class TestOutboxDispatch(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.p12 = generate_p12(password=PASSWORD.encode())[0]
		_delete_test_p12()  # restos de corridas abortadas
		cls.addClassCleanup(_delete_test_p12)
		cls.addClassCleanup(clean_pem, cls.company, "VeriFactu")
		cls.vat_account = frappe.db.get_value(
			"Account", {"company": cls.company, "account_type": "Tax", "is_group": 0}, "name"
		)

	def setUp(self):
		frappe.set_user("Administrator")
		# La clase comparte transacción: cada test arranca con la compañía en
		# estado prístino y SIN registros del libro. El rate-limit del manager
		# vive en Redis (fuera de la transacción): se limpia para que cada
		# drain arranque habilitado.
		frappe.cache().delete_keys("es_aeat_rate_limit:*")
		frappe.db.set_value(
			"Company",
			self.company,
			{
				"es_verifactu_enabled": 0,
				"es_verifactu_activation_date": None,
				"es_verifactu_credential": None,
				"es_draft_series": None,
				"es_verifactu_remission_mode": None,
				"es_verifactu_noi": None,
				"es_verifactu_batch_limit": 1000,
				"es_verifactu_timeout_seconds": 60,
				"tax_id": None,
			},
		)
		frappe.db.delete("ES Invoice Series", {"parent": self.company})
		frappe.db.delete("ES Verifactu Notification Role", {"parent": self.company})
		frappe.db.delete(LEDGER_DOCTYPE, {"company": self.company})
		for credential in frappe.get_all(
			"ES AEAT Credential", filters={"company": self.company}, pluck="name"
		):
			frappe.delete_doc("ES AEAT Credential", credential, ignore_permissions=True)

	# --- helpers de fixture (patrón de test_emision_registros.py) ------------

	def _activate(
		self,
		series: str = F1_SERIES,
		invoice_type: str = "F1",
		draft: str = DRAFT_SERIES,
		test_mode: str = "Pruebas",
		remission_mode: str = "Diferida",
	):
		"""Deja la compañía ACTIVA (compuerta completa) con el mapeo
		serie↔tipo pedido y devuelve el doc Company guardado."""
		for credential in frappe.get_all(
			"ES AEAT Credential",
			filters={"company": self.company, "purpose": "VeriFactu"},
			pluck="name",
		):
			frappe.delete_doc("ES AEAT Credential", credential, ignore_permissions=True)
		doc = frappe.get_doc("Company", self.company)
		doc.tax_id = VALID_NIF
		doc.es_verifactu_enabled = 1
		doc.es_verifactu_activation_date = ACTIVATION_DATE
		doc.es_verifactu_test_mode = test_mode
		doc.es_draft_series = draft
		doc.es_verifactu_remission_mode = remission_mode
		doc.set("es_invoice_series", [])
		doc.append("es_invoice_series", {"series": series, "invoice_type": invoice_type})
		doc.append("es_invoice_series", {"series": R1_SERIES, "invoice_type": "R1"})
		url = write_private_p12(f"es_test_remision_{frappe.generate_hash(length=8)}.p12", self.p12)
		frappe.get_doc(
			{
				"doctype": "ES AEAT Credential",
				"company": self.company,
				"purpose": "VeriFactu",
				"cert_file": url,
				"cert_password": PASSWORD,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		doc.save(ignore_permissions=True)
		return doc

	def _draft(self, **overrides):
		"""Factura mínima de la compañía de pruebas (descripción «IVA - 21» =
		patrón del contrato 07 que parsea el lobe del desglose)."""
		data = {
			"doctype": "Sales Invoice",
			"company": self.company,
			"customer": CUSTOMER,
			"naming_series": "ACC-SINV-.YYYY.-",
			"currency": "EUR",
			"posting_date": nowdate(),
			"set_posting_time": 1,
			"due_date": add_days(nowdate(), 30),
			"items": [{"item_code": ITEM, "qty": 1, "rate": 100}],
			"taxes": [
				{
					"charge_type": "On Net Total",
					"account_head": self.vat_account,
					"rate": 21,
					"description": "IVA - 21",
				}
			],
		}
		data.update(overrides)
		if (data.get("es_invoice_type") or "").startswith("R") or data.get("is_return"):
			data.setdefault("es_rectification_reason", "Rectificación de prueba")
		return frappe.get_doc(data).insert(ignore_permissions=True)

	def _invoice_records(self, invoice_name: str, **overrides):
		"""Registros del libro de una factura, ordenados por chain_index."""
		return frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"company": self.company, "sales_invoice": invoice_name, **overrides},
			fields=[
				"name",
				"record_type",
				"invoice_type",
				"chain_index",
				"hash",
				"previous_hash",
				"record_json",
				"status",
			],
			order_by="chain_index asc",
		)

	def _register_in_chain(self):
		"""Registros del libro de la empresa (cadena completa) ordenados."""
		return frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"company": self.company},
			fields=["name", "record_type", "chain_index", "hash", "status", "sales_invoice"],
			order_by="chain_index asc",
		)

	def _force_accepted_issuance(self, invoice_name: str) -> None:
		"""Simula un procesador previo por la VÍA SANCIONADA del libro
		(flag): transiciona el Alta a Correcto y denormaliza «Alta
		Aceptada» en la factura (patrón de test_emision_registros.py)."""
		record = frappe.get_doc(
			LEDGER_DOCTYPE, {"sales_invoice": invoice_name, "record_type": "RegistroAlta"}
		)
		record.flags[RESPONSE_PROCESSOR_FLAG] = True
		record.status = "Correcto"
		record.save(ignore_permissions=True)
		frappe.db.set_value(
			"Sales Invoice", invoice_name, "es_verifactu_status", emission.INVOICE_STATUS_ISSUANCE_ACCEPTED
		)

	def _adapted_seed(self, lines: list[tuple[str, str, str, object, str | None]]) -> dict:
		"""Carga la SEMILLA REAL de respuesta AEAT
		(alta_aceptada_con_errores.json — ejemplo de la referencia) y adapta
		sus RespuestaLinea a nuestros registros: misma forma de línea,
		RefExterna → docname del registro del libro.

		lines: [(external_ref, series_number, record_state, code, description)]
		"""
		seed = load_seed("alta_aceptada_con_errores")
		model = seed["RespuestaLinea"][0]
		adapted = []
		for ref, series_number, state, code, description in lines:
			line = json.loads(json.dumps(model))  # copia profunda de la forma
			line["IDFactura"]["NumSerieFactura"] = series_number
			line["RefExterna"] = ref
			line["EstadoRegistro"] = state
			line["CodigoErrorRegistro"] = code
			line["DescripcionErrorRegistro"] = description
			adapted.append(line)
		seed["RespuestaLinea"] = adapted
		return seed

	def _drain_with_mock(self, response: dict) -> MockAEATClient:
		"""Drenaje REAL (manager + driver) con el cliente mockeado que
		reproduce `response` para la operación de remisión; devuelve el
		mock (con sus sent_payloads) para inspeccionar el wire.

		ACOTADO a la compañía de prueba (drain_company): el site puede tener
		OTRAS empresas con pendientes REALES (p. ej. el registro en vivo del
		entorno de pruebas) que un drain global remitiría por el mock y cuyo
		procesado re-enlazaría registros ajenos a la respuesta del test."""
		mock = MockAEATClient(responses={OPERATION: response})
		AEATOutboxManager().drain_company(VerifactuDriver(client_factory=lambda **kw: mock), self.company)
		return mock

	# --- outbox: get_companies / get_pending (spec 04 §8) ---------------------

	def test_get_pending_ordered_and_batch_limited(self):
		"""Tres submits → tres registros PendienteEnvio ORDENADOS por
		chain_index; el límite de lote de la compañía recorta por orden de
		cadena; get_companies ve la empresa con pendientes."""
		self._activate()
		invoices = [self._draft() for _ in range(3)]
		for si in invoices:
			si.submit()

		driver = VerifactuDriver()

		self.assertIn(self.company, driver.get_companies())

		# límite de lote 2 → los DOS primeros por chain_index
		frappe.db.set_value("Company", self.company, "es_verifactu_batch_limit", 2)
		pending = driver.get_pending(self.company)
		self.assertEqual([r.chain_index for r in pending], [1, 2])
		self.assertEqual([r.sales_invoice for r in pending], [si.name for si in invoices[:2]])
		self.assertEqual([r.status for r in pending], ["PendienteEnvio", "PendienteEnvio"])
		self.assertTrue(all(r.record_json for r in pending))

		# sin recorte: la cadena completa, ordenada
		frappe.db.set_value("Company", self.company, "es_verifactu_batch_limit", 1000)
		pending = driver.get_pending(self.company)
		self.assertEqual([r.chain_index for r in pending], [1, 2, 3])
		self.assertEqual([r.sales_invoice for r in pending], [si.name for si in invoices])

	def test_get_pending_without_activation_gate(self):
		"""spec 04 §8 (regresión): lo pendiente AL DESACTIVAR sigue en el
		outbox — get_pending/get_companies NO dependen del flag «activada»."""
		self._activate()
		a = self._draft()
		a.submit()
		frappe.db.set_value("Company", self.company, "es_verifactu_enabled", 0)

		driver = VerifactuDriver()
		self.assertIn(self.company, driver.get_companies())
		pending = driver.get_pending(self.company)
		self.assertEqual(len(pending), 1)
		self.assertEqual(pending[0].status, "PendienteEnvio")

	# --- payload wire (forma de la referencia) ---------------------------------

	def test_build_payload_wire_shape(self):
		"""El payload estructurado del manager: operacion + datos con la
		Cabecera de la compañía y cada RegistroFactura ANIDADO por tipo
		({RegistroAlta: interior}) desde el record_json plano: IDFactura con
		claves AEAT, RefExterna=docname del libro, Encadenamiento
		PrimerRegistro/RegistroAnterior, y los campos del Alta."""
		self._activate()
		a, b = self._draft(), self._draft()
		a.submit()
		b.submit()

		driver = VerifactuDriver()
		records = driver.get_pending(self.company)
		payload = driver.build_payload(self.company, records)

		self.assertEqual(payload["operacion"], OPERATION)
		data = payload["datos"]
		self.assertEqual(
			data["Cabecera"],
			{
				"ObligadoEmision": {
					"NombreRazon": frappe.db.get_value("Company", self.company, "company_name"),
					"NIF": VALID_NIF,
				}
			},
		)

		first, second = data["RegistroFactura"]
		self.assertEqual(list(first), ["RegistroAlta"])

		issuance1 = first["RegistroAlta"]
		aeat_date = format_aeat_date(a.posting_date)
		self.assertEqual(
			issuance1["IDFactura"],
			{"IDEmisorFactura": VALID_NIF, "NumSerieFactura": a.name, "FechaExpedicionFactura": aeat_date},
		)
		self.assertEqual(issuance1["RefExterna"], records[0].name)
		self.assertEqual(issuance1["Encadenamiento"], {"PrimerRegistro": "S"})
		self.assertNotIn("PrimerRegistro", issuance1)  # viaja DENTRO del Encadenamiento
		self.assertEqual(issuance1["TipoFactura"], "F1")
		self.assertEqual(issuance1["Desglose"]["DetalleDesglose"][0]["TipoImpositivo"], "21")
		self.assertEqual(issuance1["CuotaTotal"], a.total_taxes_and_charges)
		self.assertEqual(issuance1["ImporteTotal"], a.rounded_total)
		self.assertEqual(issuance1["TipoHuella"], "01")
		self.assertEqual(issuance1["IDVersion"], "1.0")
		self.assertEqual(issuance1["Huella"], records[0].hash)
		self.assertTrue(issuance1["FechaHoraHusoGenRegistro"])

		# el segundo ENCADENA sobre el primero: RegistroAnterior con su
		# identidad de IDFactura y su huella
		issuance2 = second["RegistroAlta"]
		self.assertEqual(
			issuance2["Encadenamiento"],
			{
				"RegistroAnterior": {
					"IDEmisorFactura": VALID_NIF,
					"NumSerieFactura": a.name,
					"FechaExpedicionFactura": aeat_date,
					"Huella": records[0].hash,
				}
			},
		)
		self.assertEqual(issuance2["IDFactura"]["NumSerieFactura"], b.name)
		self.assertEqual(issuance2["RefExterna"], records[1].name)
		self.assertEqual(issuance2["Huella"], records[1].hash)

	def test_build_payload_complete_issuance_interior(self):
		"""Paridad del wire con el interior COMPLETO que exige el WSDL (fix
		del drenaje en vivo): DescripcionOperacion, NombreRazonEmisor,
		flags Subsanacion/RechazoPrevio/SinRegistroPrevio "N", Destinatarios
		del cliente y bloque SistemaInformatico (identidad SIF de ES
		Settings + NOI de la Company + flags L4 constantes)."""
		self._activate()
		frappe.db.set_value("Company", self.company, "es_verifactu_noi", "NOI-TEST")
		a = self._draft()
		a.submit()

		driver = VerifactuDriver()
		records = driver.get_pending(self.company)
		payload = driver.build_payload(self.company, records)
		issuance = payload["datos"]["RegistroFactura"][0]["RegistroAlta"]

		self.assertEqual(
			issuance["NombreRazonEmisor"],
			frappe.db.get_value("Company", self.company, "company_name"),
		)
		self.assertEqual(issuance["DescripcionOperacion"], f"Factura {a.name} por cantidad {a.base_total}")
		self.assertEqual(issuance["Subsanacion"], "N")
		self.assertEqual(issuance["RechazoPrevio"], "N")
		self.assertNotIn("SinRegistroPrevio", issuance)  # campo del tipo anulación
		self.assertEqual(
			issuance["Destinatarios"],
			{
				"IDDestinatario": [
					{
						"NombreRazon": a.customer_name,
						"NIF": frappe.db.get_value("Customer", CUSTOMER, "tax_id"),
					}
				]
			},
		)
		sif = emission.get_sif_data(self.company)
		self.assertEqual(issuance["SistemaInformatico"], sif)
		self.assertEqual(sif["NumeroInstalacion"], "NOI-TEST")
		self.assertEqual(sif["TipoUsoPosibleSoloVerifactu"], "S")
		self.assertEqual(sif["TipoUsoPosibleMultiOT"], "N")
		self.assertEqual(sif["IndicadorMultiplesOT"], "N")

	def test_build_payload_complete_cancellation_interior(self):
		"""Wire de la anulación: RechazoPrevio/SinRegistroPrevio "N" + el
		bloque SistemaInformatico, y SIN NombreRazonEmisor/Destinatarios/
		Desglose/montos/flags del alta (semántica propia del WSDL)."""
		self._activate()
		a = self._draft()
		a.submit()
		self._force_accepted_issuance(a.name)

		a = frappe.get_doc("Sales Invoice", a.name)
		a.cancel()

		driver = VerifactuDriver()
		records = driver.get_pending(self.company)
		payload = driver.build_payload(self.company, records)
		cancellation = payload["datos"]["RegistroFactura"][0]["RegistroAnulacion"]

		self.assertEqual(cancellation["RechazoPrevio"], "N")
		self.assertEqual(cancellation["SinRegistroPrevio"], "N")
		self.assertEqual(cancellation["SistemaInformatico"], emission.get_sif_data(self.company))
		for key in (
			"NombreRazonEmisor",
			"Destinatarios",
			"Desglose",
			"CuotaTotal",
			"ImporteTotal",
			"Subsanacion",
			"DescripcionOperacion",
		):
			self.assertNotIn(key, cancellation, key)

	def test_build_payload_enriches_legacy_record_json(self):
		"""Retrocompatibilidad (registro pre-fix, p. ej. el pendiente
		FA00001 del site): record_json SIN las claves nuevas → el driver
		ENRIQUECE el wire (NombreRazonEmisor de la Company, SIF por el
		helper, Destinatarios desde el cliente de la factura enlazada,
		DescripcionOperacion, flags "N"/"N"/"N") SIN tocar el record_json
		(fuente de verdad, spec 04 §2.2)."""
		self._activate()
		a = self._draft()
		a.submit()

		record = frappe.get_doc(
			LEDGER_DOCTYPE,
			{"sales_invoice": a.name, "record_type": "RegistroAlta"},
		)
		legacy_data = json.loads(record.record_json)
		for key in (
			"NombreRazonEmisor",
			"DescripcionOperacion",
			"Subsanacion",
			"RechazoPrevio",
			"SinRegistroPrevio",
			"Destinatarios",
			"SistemaInformatico",
		):
			legacy_data.pop(key, None)
		frappe.db.set_value(
			LEDGER_DOCTYPE,
			record.name,
			"record_json",
			json.dumps(legacy_data),
			update_modified=False,
		)

		driver = VerifactuDriver()
		records = driver.get_pending(self.company)
		payload = driver.build_payload(self.company, records)
		issuance = payload["datos"]["RegistroFactura"][0]["RegistroAlta"]

		self.assertEqual(
			issuance["NombreRazonEmisor"],
			frappe.db.get_value("Company", self.company, "company_name"),
		)
		self.assertEqual(issuance["DescripcionOperacion"], f"Factura {a.name} por cantidad {a.base_total}")
		self.assertEqual(issuance["Subsanacion"], "N")
		self.assertEqual(issuance["RechazoPrevio"], "N")
		self.assertNotIn("SinRegistroPrevio", issuance)  # campo del tipo anulación
		self.assertEqual(issuance["Destinatarios"]["IDDestinatario"][0]["NombreRazon"], a.customer_name)
		self.assertEqual(issuance["SistemaInformatico"], emission.get_sif_data(self.company))
		# el record_json del libro queda INTACTO (lo remitido ≠ lo registrado
		# solo en el enriquecimiento del wire, nunca en el libro)
		self.assertNotIn(
			"NombreRazonEmisor",
			json.loads(frappe.db.get_value(LEDGER_DOCTYPE, record.name, "record_json")),
		)

	def test_build_payload_no_invoice_no_recipients(self):
		"""Sin factura enlazada (registro manual del libro, formato
		anterior): el enriquecimiento NO inventa Destinatarios — el wire
		viaja sin el bloque (venta sin cliente / POS)."""
		self._activate()
		legacy_data = {
			"IDEmisorFactura": VALID_NIF,
			"NumSerieFactura": "MANUAL-0001",
			"FechaExpedicionFactura": "31-08-2026",
			"TipoFactura": "F1",
			"Desglose": {
				"DetalleDesglose": [
					{
						"Impuesto": "01",
						"TipoImpositivo": "21",
						"BaseImponibleOimporteNoSujeto": 100.0,
						"CuotaRepercutida": 21.0,
						"CalificacionOperacion": "S1",
						"ClaveRegimen": "01",
					}
				]
			},
			"CuotaTotal": 21.0,
			"ImporteTotal": 121.0,
			"Huella": "00" * 32,
			"FechaHoraHusoGenRegistro": "2026-08-31T12:00:00+02:00",
			"TipoHuella": "01",
			"IDVersion": "1.0",
			"PrimerRegistro": "S",
		}
		frappe.get_doc(
			{
				"doctype": LEDGER_DOCTYPE,
				"company": self.company,
				"record_type": "RegistroAlta",
				"invoice_type": "F1",
				"chain_index": 1,
				"record_json": json.dumps(legacy_data),
				"hash": legacy_data["Huella"],
				"previous_hash": "",
				"status": "PendienteEnvio",
			}
		).insert(ignore_permissions=True)

		driver = VerifactuDriver()
		records = driver.get_pending(self.company)
		payload = driver.build_payload(self.company, records)
		issuance = payload["datos"]["RegistroFactura"][0]["RegistroAlta"]

		self.assertNotIn("Destinatarios", issuance)
		self.assertEqual(issuance["Subsanacion"], "N")
		self.assertEqual(
			issuance["NombreRazonEmisor"], frappe.db.get_value("Company", self.company, "company_name")
		)
		self.assertEqual(issuance["SistemaInformatico"], emission.get_sif_data(self.company))

	def test_build_payload_pos_no_recipients(self):
		"""POS (venta por caja, tipo simplificado): el RegistroAlta NACE sin
		bloque Destinatarios («a nombre de contado») y el wire lo viaja
		sin él."""
		self._activate(series=F2_SERIES, invoice_type="F2")
		a = self._draft(
			es_invoice_type="F2",
			is_pos=1,
			payments=[{"mode_of_payment": "Cash", "amount": 121.0}],
		)
		a.submit()

		driver = VerifactuDriver()
		records = driver.get_pending(self.company)
		payload = driver.build_payload(self.company, records)
		issuance = payload["datos"]["RegistroFactura"][0]["RegistroAlta"]

		self.assertNotIn("Destinatarios", issuance)
		self.assertEqual(issuance["TipoFactura"], "F2")

	# --- drenaje completo con mock ----------------------------------------------

	def test_full_drain_transitions_ledger_and_invoices(self):
		"""Drenaje completo vía manager: lote → envío (mock con la SEMILLA
		REAL adaptada: Correcto + AceptadoConErrores 2004) → respuesta
		persistida con líneas → transiciones del libro por la VÍA SANCIONADA
		(flag) + enlace a la respuesta + codigo_error → facturas
		denormalizadas con el mapper de emission.py."""
		self._activate()
		a, b = self._draft(), self._draft()
		a.submit()
		b.submit()

		names = [r.name for r in self._register_in_chain()]
		response = self._adapted_seed(
			[
				(names[0], a.name, "Correcto", None, None),
				(
					names[1],
					b.name,
					"AceptadoConErrores",
					2004,
					"El valor del campo FechaHoraHusoGenRegistro debe ser la fecha actual del sistema de la AEAT.",
				),
			]
		)
		mock = self._drain_with_mock(response)

		# libro: transiciones terminales + enlace + error de la línea
		ra = frappe.get_doc(LEDGER_DOCTYPE, names[0])
		self.assertEqual(ra.status, "Correcto")
		self.assertFalse(ra.response_error_code)
		rb = frappe.get_doc(LEDGER_DOCTYPE, names[1])
		self.assertEqual(rb.status, "AceptadoConErrores")
		self.assertEqual(rb.response_error_code, "2004")
		self.assertIn("FechaHoraHusoGenRegistro", rb.response_error_msg)

		# facturas denormalizadas (mapper canónico de emission.py)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_ISSUANCE_ACCEPTED,
		)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", b.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_ISSUANCE_WITH_ERRORS,
		)

		# respuesta persistida (la persistió el MANAGER) + líneas normalizadas
		resp = frappe.get_doc(RESPONSE_DOCTYPE, ra.response)
		self.assertEqual(resp.service, "VeriFactu")
		self.assertEqual(resp.company, self.company)
		self.assertEqual(resp.send_state, "ParcialmenteCorrecto")
		self.assertEqual(resp.csv, "A-EXAMPLECSV00001")
		self.assertEqual(resp.tiempo_espera_envio, 60)
		self.assertEqual([l.external_ref for l in resp.lines], names)
		self.assertEqual([l.record_state for l in resp.lines], ["Correcto", "AceptadoConErrores"])
		self.assertEqual([l.operation_type for l in resp.lines], ["Alta", "Alta"])
		self.assertEqual(rb.response, str(resp.name))

		# el envío fue UN lote con los DOS registros, en orden de cadena
		self.assertEqual(len(mock.sent_payloads), 1)
		sent = mock.sent_payloads[0]
		self.assertEqual(sent["operacion"], OPERATION)
		self.assertEqual(len(sent["datos"]["RegistroFactura"]), 2)

	def test_drain_after_deactivation_still_sends(self):
		"""spec 04 §8 (regresión): la compañía se DESACTIVA con pendientes y
		el drenaje SIGUE remitiéndolos (el outbox no depende del flag)."""
		self._activate()
		a = self._draft()
		a.submit()
		frappe.db.set_value("Company", self.company, "es_verifactu_enabled", 0)

		name = self._invoice_records(a.name)[0].name
		self._drain_with_mock(self._adapted_seed([(name, a.name, "Correcto", None, None)]))

		record = frappe.get_doc(LEDGER_DOCTYPE, name)
		self.assertEqual(record.status, "Correcto")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_ISSUANCE_ACCEPTED,
		)

	# --- anulación (spec 04 §6): línea Anulacion → RegistroAnulacion ----------

	def test_cancellation_drained(self):
		"""La cancelación genera su RegistroAnulacion PendienteEnvio; el
		drenaje remite su wire ({RegistroAnulacion: {IDFactura con claves
		*Anulada, Encadenamiento sobre el alta}}) y la línea de respuesta
		Anulacion/Correcto lo transiciona + denormaliza «Anulada»."""
		self._activate()
		a = self._draft()
		a.submit()
		issuance = self._invoice_records(a.name, record_type="RegistroAlta")[0]
		self._force_accepted_issuance(a.name)

		a = frappe.get_doc("Sales Invoice", a.name)
		a.cancel()

		cancellation = self._invoice_records(a.name, record_type="RegistroAnulacion")[0]
		self.assertEqual(cancellation.status, "PendienteEnvio")

		response = self._adapted_seed([(cancellation.name, a.name, "Correcto", None, None)])
		response["RespuestaLinea"][0]["Operacion"]["TipoOperacion"] = "Anulacion"
		mock = self._drain_with_mock(response)

		# registro anulado por la respuesta (misma vía sancionada)
		record = frappe.get_doc(LEDGER_DOCTYPE, cancellation.name)
		self.assertEqual(record.status, "Correcto")
		self.assertTrue(frappe.db.exists(RESPONSE_DOCTYPE, record.response))
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_CANCELLED,
		)

		# wire de la anulación: envoltorio por tipo + IDFactura Anulada +
		# Encadenamiento sobre el alta
		aeat_date = format_aeat_date(a.posting_date)
		element = mock.sent_payloads[0]["datos"]["RegistroFactura"][0]
		self.assertEqual(list(element), ["RegistroAnulacion"])
		annulment = element["RegistroAnulacion"]
		self.assertEqual(
			annulment["IDFactura"],
			{
				"IDEmisorFacturaAnulada": VALID_NIF,
				"NumSerieFacturaAnulada": a.name,
				"FechaExpedicionFacturaAnulada": aeat_date,
			},
		)
		self.assertEqual(annulment["RefExterna"], cancellation.name)
		self.assertEqual(
			annulment["Encadenamiento"],
			{
				"RegistroAnterior": {
					"IDEmisorFactura": VALID_NIF,
					"NumSerieFactura": a.name,
					"FechaExpedicionFactura": aeat_date,
					"Huella": issuance.hash,
				}
			},
		)
		self.assertEqual(annulment["Huella"], cancellation.hash)
		self.assertEqual(annulment["TipoHuella"], "01")
		self.assertEqual(annulment["IDVersion"], "1.0")

	# --- SOAP Fault → líneas sintéticas (cliente) → Incorrecto ----------------

	def test_soap_fault_synthetic_lines_reject_records(self):
		"""Un SOAP Fault de la AEAT (conversión del cliente a líneas
		sintéticas, mismo camino de producción) drena a Incorrecto: los
		registros del libro con codigo_error, la respuesta con fault_code/
		message, y las facturas SIN estado terminal del mapper (su
		corrección es la subsanación — lote 5b)."""
		self._activate()
		a, b = self._draft(), self._draft()
		a.submit()
		b.submit()

		# el Fault se convierte con la función REAL del cliente sobre el
		# payload REAL del driver (fidelidad del camino de producción)
		driver = VerifactuDriver()
		records = driver.get_pending(self.company)
		payload = driver.build_payload(self.company, records)
		fault = Fault("Registro de facturación duplicado. Codigo[3000]", code=1000)
		response = _fault_to_synthetic_response("VeriFactu", fault, payload["datos"])

		names = [r.name for r in self._register_in_chain()]
		self._drain_with_mock(response)

		for name in names:
			record = frappe.get_doc(LEDGER_DOCTYPE, name)
			self.assertEqual(record.status, "Incorrecto")
			self.assertEqual(record.response_error_code, "3000")
			self.assertIn("duplicado", (record.response_error_msg or "").lower())

		# factura sin estado terminal del mapper: sigue Pendiente Envío
		for si in (a, b):
			self.assertEqual(
				frappe.db.get_value("Sales Invoice", si.name, "es_verifactu_status"),
				emission.INVOICE_STATUS_PENDING_SEND,
			)

		# respuesta persistida con el fault y sus líneas sintéticas
		resp = frappe.get_doc(RESPONSE_DOCTYPE, frappe.get_doc(LEDGER_DOCTYPE, names[0]).response)
		self.assertEqual(resp.send_state, "Incorrecto")
		self.assertEqual(resp.fault_code, "1000")
		self.assertIn("Codigo[3000]", resp.fault_message)
		self.assertEqual([l.external_ref for l in resp.lines], names)
		self.assertEqual([l.record_state for l in resp.lines], ["Incorrecto", "Incorrecto"])

	# --- aislamiento de errores permanentes (spec 13 §5) -----------------------

	def test_permanent_error_isolated_per_company(self):
		"""Error PERMANENTE del driver real (sin credencial → get_client
		rebota, sin reintento): queda aislado por empresa en el manager
		(log_error) y NO aborta el drenaje del resto (el driver con cliente
		mockeado drena normal; los registros del fallido quedan intactos
		como PendienteEnvio hasta la próxima corrida)."""
		self._activate()
		a = self._draft()
		a.submit()
		name = self._invoice_records(a.name)[0].name

		# se retira la credencial: el driver REAL rebota al construir cliente
		for credential in frappe.get_all(
			"ES AEAT Credential", filters={"company": self.company}, pluck="name"
		):
			frappe.delete_doc("ES AEAT Credential", credential, ignore_permissions=True)

		mock = MockAEATClient(
			responses={OPERATION: self._adapted_seed([(name, a.name, "Correcto", None, None)])}
		)
		# dos «empresas» del drenaje: el error del driver sin credencial no
		# aborta la corrida — el siguiente drena normal (spec 13 §5). El
		# drenaje se ACOTA a la compañía de prueba (get_companies parcheado):
		# el site tiene OTRAS empresas con pendientes REALES (registro en
		# vivo del entorno de pruebas) que el driver real remitiría de
		# verdad a la AEAT.
		real = VerifactuDriver()
		with_mock = VerifactuDriver(client_factory=lambda **kw: mock)
		with (
			unittest.mock.patch.object(real, "get_companies", return_value=[self.company]),
			unittest.mock.patch.object(with_mock, "get_companies", return_value=[self.company]),
		):
			AEATOutboxManager().drain([real, with_mock])

		self.assertTrue(
			frappe.get_all(
				"Error Log",
				filters={"method": f"AEAT VeriFactu: error drenando {self.company}"},
				pluck="name",
			),
			"se esperaba frappe.log_error del aislamiento por empresa",
		)
		record = frappe.get_doc(LEDGER_DOCTYPE, name)
		self.assertEqual(record.status, "Correcto")  # drenado por el otro driver
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_ISSUANCE_ACCEPTED,
		)

	# --- planificador (hooks) ----------------------------------------------------

	def test_hooks_scheduler_cron_drain(self):
		"""El planificador drena el outbox cada minuto (spec 04 §8): la
		entrada cron (formato de 5 campos de frappe v16) existe y la tarea
		es resoluble por su vía real. Se consulta con app_name (carga fresca
		de los hooks en disco, sin el cache de Redis)."""
		hooks = frappe.get_hooks("scheduler_events", app_name="erpnext_spain")
		cron_entries = hooks.get("cron") or {}
		self.assertIn(
			"erpnext_spain.es_verifactu.tasks.drain_outbox",
			cron_entries.get("* * * * *", []),
		)
		self.assertTrue(callable(frappe.get_attr("erpnext_spain.es_verifactu.tasks.drain_outbox")))
		self.assertTrue(callable(frappe.get_attr("erpnext_spain.es_verifactu.tasks.send_pending")))
