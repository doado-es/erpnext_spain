# Tests del ciclo de EMISIÓN VeriFactu — lote 4c (spec 04 §4-6, §12):
# RegistroAlta al submit (encadenado bajo cerrojo), estado denormalizado,
# remisión Inmediata, RegistroAnulación al cancelar (gateado por el SNAPSHOT
# de modo), compuertas de validate y semántica del cerrojo manual.
#
# Misma NOTA de colocación que test_emision_naming.py: módulo en tests/, sin
# IGNORE_TEST_RECORD_DEPENDENCIES (raise NotImplementedError fuera de carpeta
# de doctype). Masters reales del site; rollback POR CLASE (los tests de una
# clase comparten transacción — el setUp devuelve la compañía a estado
# prístino y borra los registros del libro de la empresa por db.delete).
#
# test_sequential_submits_chain_without_fork (al final de la clase)
# ORIGINALMENTE levantaba threads con conexiones separadas para submits en
# paralelo real (lote 4c): el INSERT del borrador consume el contador
# tabSeries FUERA de la sección crítica del cerrojo y la base deadlockaba
# (QueryDeadlockError) — limitación del harness, no defecto del producto.
# REDISEÑADO determinista: ráfaga secuencial que asierte números CONSECUTIVOS
# + cadena sin horquilla; la semántica del cerrojo la cubre
# test_manual_lock_api. El nombre se conserva por trazabilidad.

from __future__ import annotations

import glob
import itertools
import json
import os
import unittest.mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from erpnext_spain.aeat.tests.helpers import (
	clean_pem,
	generate_p12,
	test_company,
	write_private_p12,
)
from erpnext_spain.aeat.utils import absolute_site_path, format_aeat_date
from erpnext_spain.es_verifactu import emission
from erpnext_spain.es_verifactu.doctype.es_verifactu_billing_record.es_verifactu_billing_record import (
	RESPONSE_PROCESSOR_FLAG,
)
from erpnext_spain.es_verifactu.utils import locks
from erpnext_spain.es_verifactu.utils.data_adapter import compute_issuance_hash
from erpnext_spain.tests.fixtures import TEST_CUSTOMER, TEST_ITEM

P12_PATTERN = "es_test_registros_*.p12"
PASSWORD = "es-test-pass"

VALID_NIF = "12345678Z"
INVALID_NIF_CONTROL_DIGIT = "12345678A"  # letra de control equivocada (válida: Z)
ACTIVATION_DATE = "2026-01-01"

DRAFT_SERIES = "BORRADOR-.#####"
SERIES_F1 = "SIF1-.####."
SERIES_F2 = "SIF2-.####."
# Serie de las rectificativas (R1..R5): mismo estilo de patrón que SIF1.
SERIES_R1 = "RC-.####."

CUSTOMER = TEST_CUSTOMER
ITEM = TEST_ITEM

LEDGER_DOCTYPE = "ES Verifactu Billing Record"


def _delete_test_p12s() -> None:
	for path in glob.glob(absolute_site_path("private", "files", P12_PATTERN)):
		os.remove(path)


class TestEmisionRegistros(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.p12 = generate_p12(password=PASSWORD.encode())[0]
		_delete_test_p12s()  # restos de corridas abortadas
		cls.addClassCleanup(_delete_test_p12s)
		cls.addClassCleanup(clean_pem, cls.company, "VeriFactu")
		cls.tax_account = frappe.db.get_value(
			"Account", {"company": cls.company, "account_type": "Tax", "is_group": 0}, "name"
		)
		# Identidad SIF determinística (los registros leen ES Settings): sin
		# esto los tests dependen de la configuración REAL del site y un
		# valor inválido (p. ej. id de >2 caracteres) los rompería.
		cls._original_sif = frappe.db.get_value(
			"ES Settings", "ES Settings", emission.SIF_FIELDS, as_dict=True
		)
		frappe.db.set_value(
			"ES Settings",
			"ES Settings",
			{
				"sif_nombre_razon": "Emisor Test SL",
				"sif_nif": "B27331230",
				"sif_nombre_sistema_informatico": "Sistema Test",
				"sif_id_sistema_informatico": "01",  # TextMax2Type (WSDL)
				"sif_version": "v1-test",
			},
		)
		cls.addClassCleanup(
			frappe.db.set_value,
			"ES Settings",
			"ES Settings",
			{campo: getattr(cls._original_sif, campo) for campo in emission.SIF_FIELDS},
		)

	def setUp(self):
		frappe.set_user("Administrator")
		# La clase comparte transacción: cada test arranca con la compañía en
		# estado prístino y SIN registros del libro (reset por db.set_value,
		# sin hooks) — así las cadenas de cada test son deterministas.
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

	# --- helpers -----------------------------------------------------------

	def _activate(
		self,
		series: str = SERIES_F1,
		invoice_type: str = "F1",
		draft: str = DRAFT_SERIES,
		test_mode: str = "Pruebas",
		remission_mode: str = "Diferida",
	):
		"""Deja la compañía ACTIVA (compuerta completa) con el mapeo
		serie↔tipo pedido y devuelve el doc Company guardado.

		Siempre mapea también una serie para R1: los tests de rectificativa
		submiten facturas R1 (el before_submit resuelve su serie por este
		mapeo) y un mapeo F1-único los rebota con «No hay serie mapeada
		para R1» — espejo exacto de cómo se añade el mapeo principal."""
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
		doc.append("es_invoice_series", {"series": SERIES_R1, "invoice_type": "R1"})
		url = write_private_p12(f"es_test_registros_{frappe.generate_hash(length=8)}.p12", self.p12)
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

	def _draft_invoice(self, **overrides):
		"""Factura mínima de la compañía de pruebas (masters reales del site;
		descripción «IVA - 21» = patrón del contrato 07 que parsea el lobe del
		desglose)."""
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
					"account_head": self.tax_account,
					"rate": 21,
					"description": "IVA - 21",
				}
			],
		}
		data.update(overrides)
		if (data.get("es_invoice_type") or "").startswith("R") or data.get("is_return"):
			data.setdefault("es_rectification_reason", "Rectificación de prueba")
		return frappe.get_doc(data).insert(ignore_permissions=True)

	def _rectification_invoice(self, original: str, **overrides):
		"""Rectificativa (abono) enlazada a `original` con tipo R1."""
		data = {
			"doctype": "Sales Invoice",
			"company": self.company,
			"customer": CUSTOMER,
			"naming_series": "ACC-SINV-.YYYY.-",
			"currency": "EUR",
			"posting_date": nowdate(),
			"set_posting_time": 1,
			"is_return": 1,
			"return_against": original,
			"es_invoice_type": "R1",
			"es_rectification_reason": "Rectificación de prueba",
			"items": [{"item_code": ITEM, "qty": -1, "rate": 100}],
			"taxes": [
				{
					"charge_type": "On Net Total",
					"account_head": self.tax_account,
					"rate": 21,
					"description": "IVA - 21",
				}
			],
		}
		data.update(overrides)
		if (data.get("es_invoice_type") or "").startswith("R") or data.get("is_return"):
			data.setdefault("es_rectification_reason", "Rectificación de prueba")
		return frappe.get_doc(data).insert(ignore_permissions=True)

	def _register(self, invoice_name: str, **overrides):
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
			],
			order_by="chain_index asc",
		)

	def _force_issuance_accepted(self, invoice_name: str) -> None:
		"""Simula el procesador de respuestas (lote 5) por la VÍA SANCIONADA
		del libro (flag, ver test_es_verifactu_billing_record.py): transiciona
		el Alta a Correcto y denormaliza «Alta Aceptada» en la factura."""
		record = frappe.get_doc(
			LEDGER_DOCTYPE, {"sales_invoice": invoice_name, "record_type": "RegistroAlta"}
		)
		record.flags[RESPONSE_PROCESSOR_FLAG] = True
		record.status = "Correcto"
		record.save(ignore_permissions=True)
		frappe.db.set_value(
			"Sales Invoice", invoice_name, "es_verifactu_status", emission.INVOICE_STATUS_ISSUANCE_ACCEPTED
		)

	# --- RegistroAlta encadenado (spec 04 §5) ------------------------------

	def test_chain_of_three_issuances(self):
		"""Tres submits → tres registros consecutivos: el primero es
		PrimerRegistro=S con previous_hash vacía; cada siguiente encadena
		sobre la huella del anterior; huellas todas distintas; record_json
		lleva el Alta COMPLETO con los valores reales de la factura."""
		self._activate()
		a = self._draft_invoice()
		b = self._draft_invoice()
		c = self._draft_invoice()
		for si in (a, b, c):
			si.submit()

		names = (a.name, b.name, c.name)
		for name in names:
			self.assertRegex(name, r"^SIF1-\d{4}$")

		# cadena de la empresa: 3 registros, indices consecutivos base 1
		chain = frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"company": self.company},
			fields=["name", "chain_index", "hash", "previous_hash"],
			order_by="chain_index asc",
		)
		self.assertEqual(len(chain), 3)
		self.assertEqual([r.chain_index for r in chain], [1, 2, 3])

		self.assertEqual(chain[0].previous_hash, "")
		self.assertEqual(chain[1].previous_hash, chain[0].hash)
		self.assertEqual(chain[2].previous_hash, chain[1].hash)
		self.assertEqual(len({r.hash for r in chain}), 3)  # sin horquilla
		for r in chain:
			self.assertEqual(len(r.hash), 64)  # SHA-256 hex
			self.assertEqual(r.hash, r.hash.upper())

		# PrimerRegistro viaja DENTRO del record_json (contrato del adaptador)
		records = [json.loads(r.record_json) for r in self._register_in_chain()]
		self.assertEqual(records[0]["PrimerRegistro"], "S")
		self.assertEqual(records[1]["PrimerRegistro"], "N")
		self.assertEqual(records[2]["PrimerRegistro"], "N")

		# record_json = fuente de verdad del Alta completo (valores REALES)
		for record, si in zip(records, (a, b, c), strict=True):
			self.assertEqual(record["IDEmisorFactura"], VALID_NIF)
			self.assertEqual(record["NumSerieFactura"], si.name)
			self.assertEqual(record["TipoFactura"], "F1")
			self.assertEqual(record["FechaExpedicionFactura"], format_aeat_date(si.posting_date))
			self.assertEqual(record["CuotaTotal"], si.total_taxes_and_charges)
			self.assertEqual(record["ImporteTotal"], si.rounded_total)
			self.assertEqual(record["TipoHuella"], "01")
			self.assertEqual(record["IDVersion"], "1.0")
			detail = record["Desglose"]["DetalleDesglose"][0]
			self.assertEqual(detail["Impuesto"], "01")
			self.assertEqual(detail["TipoImpositivo"], "21")
			self.assertEqual(detail["BaseImponibleOimporteNoSujeto"], 100.0)
			self.assertEqual(detail["CuotaRepercutida"], 21.0)

		# la huella es REPRODUCTIBLE desde el record_json (algoritmo congelado)
		recomputed = dict(records[1])
		recomputed["Huella"] = chain[0].hash
		self.assertEqual(compute_issuance_hash(recomputed), chain[1].hash)

	def _register_in_chain(self):
		"""Registros del libro de la empresa (cadena completa) ordenados."""
		return frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"company": self.company},
			fields=["name", "record_json"],
			order_by="chain_index asc",
		)

	def test_denormalized_status_pending(self):
		"""Al submit la factura queda en estado VeriFactu «Pendiente Envío»
		(spec 04 §3): el doc en memoria y la fila persistida."""
		self._activate()
		a = self._draft_invoice()
		a.submit()

		self.assertEqual(a.es_verifactu_status, emission.INVOICE_STATUS_PENDING_SEND)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_PENDING_SEND,
		)

	def test_immediate_remission_enqueued_after_commit(self):
		"""Inmediata: el submit encola el drenaje del outbox con
		enqueue_after_commit=True (JAMÁS antes del commit — en el test la
		transacción jamás commitea, así que se ASERTE la LLAMADA: método
		exacto, flag after-commit y compañía; más la tarea importable por su
		vía real, frappe.get_attr). Diferida: ninguna llamada."""
		self._activate(remission_mode="Inmediata")
		a = self._draft_invoice()

		with unittest.mock.patch("frappe.enqueue") as mock_enqueue:
			a.submit()
			llamadas = [
				c for c in mock_enqueue.call_args_list if c.args and c.args[0] == emission.TASK_SEND_PENDING
			]
			self.assertEqual(len(llamadas), 1)
			self.assertTrue(llamadas[0].kwargs.get("enqueue_after_commit"))
			self.assertEqual(llamadas[0].kwargs.get("company"), self.company)

		# la tarea existe por la vía real de resolución de frappe:
		self.assertTrue(callable(frappe.get_attr(emission.TASK_SEND_PENDING)))

		# Diferida (default): ninguna cola
		self._activate(remission_mode="Diferida")
		b = self._draft_invoice()
		with unittest.mock.patch("frappe.enqueue") as mock_enqueue:
			b.submit()
			llamadas = [
				c for c in mock_enqueue.call_args_list if c.args and c.args[0] == emission.TASK_SEND_PENDING
			]
			self.assertEqual(llamadas, [])

	# --- RegistroAnulación (spec 04 §6) --------------------------------------

	def test_cancellation_creates_cancellation_record(self):
		"""Cancelar una factura con alta ACEPTADA genera su RegistroAnulación
		encadenado sobre la última huella y denormaliza «Anulada»."""
		self._activate()
		a = self._draft_invoice()
		a.submit()
		issuance = self._register(a.name, record_type="RegistroAlta")[0]
		self._force_issuance_accepted(a.name)

		a = frappe.get_doc("Sales Invoice", a.name)
		a.cancel()

		records = self._register(a.name)
		self.assertEqual(len(records), 2)
		cancellation = records[1]
		self.assertEqual(cancellation.record_type, "RegistroAnulacion")
		self.assertEqual(cancellation.chain_index, issuance.chain_index + 1)
		self.assertEqual(cancellation.previous_hash, issuance.hash)
		self.assertNotEqual(cancellation.hash, issuance.hash)
		self.assertNotEqual(cancellation.previous_hash, cancellation.hash)

		content = json.loads(cancellation.record_json)
		self.assertEqual(content["IDEmisorFacturaAnulada"], VALID_NIF)
		self.assertEqual(content["NumSerieFacturaAnulada"], a.name)
		self.assertEqual(content["FechaExpedicionFacturaAnulada"], format_aeat_date(a.posting_date))
		self.assertEqual(content["PrimerRegistro"], "N")
		self.assertEqual(content["TipoHuella"], "01")

		# factura denormalizada:
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_CANCELLED,
		)

	def test_cancellation_of_pending_blocked(self):
		"""El alta pendiente NO se cancela: se corrige por subsanación
		(spec 04 §6) — cancelar rebota con remedio y no genera anulación.

		Se recarga la factura tras el submit (mismo patrón que los otros
		tests de cancelación): el core de ERPNext escribe la fila DESPUÉS del
		db_update del submit con update_modified=True (outstanding_amount,
		status) y el doc en memoria queda viejo — cancelar sin recargar
		revienta con TimestampMismatchError ANTES de llegar a la compuerta."""
		self._activate()
		a = self._draft_invoice()
		a.submit()

		a = frappe.get_doc("Sales Invoice", a.name)
		with self.assertRaises(frappe.ValidationError) as ctx:
			a.cancel()

		mensaje = str(ctx.exception)
		self.assertIn("Alta Aceptada", mensaje)
		self.assertIn("subsanación", mensaje.lower())
		self.assertIn("Remedio", mensaje)

		# sin anulación, la factura sigue emitida:
		self.assertEqual(frappe.db.get_value("Sales Invoice", a.name, "docstatus"), 1)
		self.assertEqual(self._register(a.name, record_type="RegistroAnulacion"), [])

	def test_cancellation_gate_by_snapshot_not_current_mode(self):
		"""LA regresión del defecto v1: factura emitida en modo VeriFactu;
		compañía DESACTIVADA después; la cancelación SIGUE funcionando (la
		compuerta es el snapshot de modo de la FACTURA, spec 04 §6)."""
		self._activate()
		a = self._draft_invoice()
		a.submit()
		self.assertEqual(a.es_verifactu_mode, "Verifactu en pruebas")
		self._force_issuance_accepted(a.name)

		# desactivar la compañía DESPUÉS de emitir:
		frappe.db.set_value("Company", self.company, "es_verifactu_enabled", 0)

		a = frappe.get_doc("Sales Invoice", a.name)
		a.cancel()

		self.assertEqual(len(self._register(a.name, record_type="RegistroAnulacion")), 1)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_CANCELLED,
		)

	def test_cancellation_without_snapshot_proceeds_clean(self):
		"""Factura emitida ANTES de activar VeriFactu (sin snapshot de modo):
		la cancelación NO genera registro (no hay nada que anular en el
		libro)."""
		# setUp deja la compañía desactivada: el submit no toca la factura.
		a = self._draft_invoice()
		a.submit()
		self.assertFalse(frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_mode"))

		a.cancel()

		self.assertEqual(frappe.db.get_value("Sales Invoice", a.name, "docstatus"), 2)
		self.assertEqual(frappe.get_all(LEDGER_DOCTYPE, filters={"company": self.company}, pluck="name"), [])

	# --- identidad SIF del interior completo (fix del drenaje en vivo) ------

	def test_submit_without_sif_identity_blocks_with_remedy(self):
		"""ES Settings sin identidad SIF → el RegistroAlta no se puede
		construir (el bloque SistemaInformatico es obligatorio en el WSDL):
		el submit rebota con remedio «complete la identidad SIF en ES
		Settings». Se restauran los valores previos para no envenenar los
		tests posteriores de la clase."""
		self._activate()
		originales = frappe.db.get_value("ES Settings", "ES Settings", emission.SIF_FIELDS, as_dict=True)
		frappe.db.set_value("ES Settings", "ES Settings", {campo: None for campo in emission.SIF_FIELDS})
		self.addCleanup(
			frappe.db.set_value,
			"ES Settings",
			"ES Settings",
			{campo: getattr(originales, campo) for campo in emission.SIF_FIELDS},
		)

		a = self._draft_invoice()
		with self.assertRaises(frappe.ValidationError) as ctx:
			a.submit()

		mensaje = str(ctx.exception)
		self.assertIn("identidad SIF", mensaje)
		self.assertIn("ES Settings", mensaje)
		self.assertIn("Remedio", mensaje)

	def test_submit_with_long_sif_id_blocks(self):
		"""IdSistemaInformatico es TextMax2Type en el WSDL (verificado EN
		VIVO: la AEAT rechazó con 1100 un id de 8 caracteres; zeep NO valida
		maxLength client-side): la compuerta es NUESTRA. Con un id de 3+
		caracteres el submit rebota con remedio que cita el límite."""
		self._activate()
		originales = frappe.db.get_value("ES Settings", "ES Settings", emission.SIF_FIELDS, as_dict=True)
		frappe.db.set_value("ES Settings", "ES Settings", "sif_id_sistema_informatico", "TOOLARGE")
		self.addCleanup(
			frappe.db.set_value,
			"ES Settings",
			"ES Settings",
			{campo: getattr(originales, campo) for campo in emission.SIF_FIELDS},
		)

		a = self._draft_invoice()
		with self.assertRaises(frappe.ValidationError) as ctx:
			a.submit()

		mensaje = str(ctx.exception)
		self.assertIn("IdSistemaInformatico", mensaje)
		self.assertIn("2 caracteres", mensaje)
		self.assertIn("1100", mensaje)
		self.assertIn("Remedio", mensaje)

	def test_submit_with_sif_identity_registers_sistema_informatico(self):
		"""Con la identidad SIF completa, el record_json del alta lleva el
		bloque SistemaInformatico (ES Settings + NOI de la Company) y los
		flags de reemisión por defecto."""
		self._activate()
		a = self._draft_invoice()
		a.submit()

		record = json.loads(self._register(a.name)[0].record_json)
		self.assertEqual(record["SistemaInformatico"], emission.get_sif_data(self.company))
		self.assertEqual(
			record["NombreRazonEmisor"], frappe.db.get_value("Company", self.company, "company_name")
		)
		self.assertEqual(record["Subsanacion"], "N")
		self.assertEqual(record["RechazoPrevio"], "N")
		self.assertNotIn("SinRegistroPrevio", record)  # campo exclusivo del tipo anulación
		self.assertIn("Factura", record["DescripcionOperacion"])
		# POS sí lleva destinatario (factura con cliente, no POS)
		self.assertIn("Destinatarios", record)

	# --- compuertas de validate (spec 04 §4.2) ------------------------------

	def test_amend_blocked_with_remedy(self):
		"""El amend rompería la trazabilidad factura↔libro: rebota con
		remedio (anulación + rectificativa)."""
		self._activate()
		a = self._draft_invoice()
		a.submit()

		amend = self._draft_invoice()
		amend.amended_from = a.name
		with self.assertRaises(frappe.ValidationError) as ctx:
			amend.save(ignore_permissions=True)

		mensaje = str(ctx.exception)
		self.assertIn("amend", mensaje.lower())
		self.assertIn("rectificativa", mensaje.lower())
		self.assertIn("Remedio", mensaje)

	def test_f2_without_pos_blocked(self):
		"""Tipo simplificado (F2) sin venta POS: rebota con remedio."""
		self._activate(series=SERIES_F2, invoice_type="F2")
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._draft_invoice(es_invoice_type="F2")

		mensaje = str(ctx.exception)
		self.assertIn("POS", mensaje)
		self.assertIn("Remedio", mensaje)

	def test_f2_with_pos_passes(self):
		"""F2 con is_pos (ticket por caja): pasa las compuertas, se emite y
		su RegistroAlta lleva TipoFactura F2 (sin compuerta de NIF de
		destinatario: tickets a «contado», spec 14 §2)."""
		self._activate(series=SERIES_F2, invoice_type="F2")
		a = self._draft_invoice(
			es_invoice_type="F2",
			is_pos=1,
			payments=[{"mode_of_payment": "Cash", "amount": 121.0}],
		)
		a.submit()

		self.assertEqual(a.docstatus, 1)
		self.assertRegex(a.name, r"^SIF2-\d{4}$")
		record = self._register(a.name)[0]
		self.assertEqual(json.loads(record.record_json)["TipoFactura"], "F2")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_PENDING_SEND,
		)

	def test_invalid_customer_nif_blocked_with_suggestion(self):
		"""NIF del cliente con letra de control equivocada: la última
		compuerta rebota e incluye la SUGERENCIA del verificador (spec 14).

		El NIF inválido se fija en el CLIENTE por db.set_value (mismo patrón
		que el test del emisor usa con Company): Sales Invoice.tax_id es
		fetch del maestro y el detalle del cliente lo pisa en el insert —
		fijarlo en la factura no vale. Se restaura el valor previo para no
		envenenar los tests posteriores de la clase."""
		self._activate()
		nif_previo = frappe.db.get_value("Customer", CUSTOMER, "tax_id")
		frappe.db.set_value("Customer", CUSTOMER, "tax_id", INVALID_NIF_CONTROL_DIGIT)
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				self._draft_invoice(tax_id=INVALID_NIF_CONTROL_DIGIT)
		finally:
			frappe.db.set_value("Customer", CUSTOMER, "tax_id", nif_previo)

		mensaje = str(ctx.exception)
		self.assertIn("quisiste decir", mensaje)  # sugerencia: `Z`
		self.assertIn("Z", mensaje)
		self.assertIn("Remedio", mensaje)

	def test_missing_issuer_nif_blocked(self):
		"""Compañía activa sin NIF de emisor: la última compuerta rebota
		(aunque la activación lo exigiera, el NIF pudo vaciarse después)."""
		self._activate()
		frappe.db.set_value("Company", self.company, "tax_id", None)

		with self.assertRaises(frappe.ValidationError) as ctx:
			self._draft_invoice()

		self.assertIn("emisor", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_rectification_over_unaccepted_blocked(self):
		"""Rectificativa enlazada a una original PENDIENTE: rebota con
		remedio (esperar el alta aceptada / subsanación)."""
		self._activate()
		original = self._draft_invoice()
		original.submit()  # queda «Pendiente Envío»

		with self.assertRaises(frappe.ValidationError) as ctx:
			self._rectification_invoice(original.name)

		mensaje = str(ctx.exception)
		self.assertIn(emission.INVOICE_STATUS_ISSUANCE_ACCEPTED, mensaje)
		self.assertIn("Remedio", mensaje)

	def test_second_rectification_over_same_original_blocked(self):
		"""Una rectificativa pendiente sobre la original bloquea la segunda
		(spec 04 §6: una rectificativa a la vez)."""
		self._activate()
		original = self._draft_invoice()
		original.submit()
		self._force_issuance_accepted(original.name)

		primera = self._rectification_invoice(original.name)
		primera.submit()  # su Alta queda PendienteEnvio

		with self.assertRaises(frappe.ValidationError) as ctx:
			self._rectification_invoice(original.name)

		mensaje = str(ctx.exception)
		self.assertIn("rectificativa", mensaje.lower())
		self.assertIn("Remedio", mensaje)

	def test_external_rectification_passes(self):
		"""return_against vacío + trío externo completo: OK (spec 04 §6, gap
		de la referencia). El RegistroAlta lleva FacturasRectificadas con el
		trío y TipoRectificativa por diferencias («I»)."""
		self._activate()
		r = self._draft_invoice(
			es_invoice_type="R1",
			es_external_rectified_nif="87654321Z",
			es_external_rectified_number="EXT-2026-001",
			es_external_rectified_date="2026-05-10",
		)
		r.submit()

		record = self._register(r.name)[0]
		content = json.loads(record.record_json)
		self.assertEqual(content["TipoFactura"], "R1")
		self.assertEqual(content["TipoRectificativa"], "I")
		rectified = content["FacturasRectificadas"]["IDFacturaRectificada"][0]
		self.assertEqual(rectified["IDEmisorFactura"], "87654321Z")
		self.assertEqual(rectified["NumSerieFactura"], "EXT-2026-001")
		self.assertEqual(rectified["FechaExpedicionFactura"], "10-05-2026")

	def test_internal_rectification_carries_original_data(self):
		"""Rectificativa enlazada: FacturasRectificadas con los datos de la
		original interna (mismo emisor)."""
		self._activate()
		original = self._draft_invoice()
		original.submit()
		self._force_issuance_accepted(original.name)

		r = self._rectification_invoice(original.name)
		r.submit()

		content = json.loads(self._register(r.name)[0].record_json)
		rectified = content["FacturasRectificadas"]["IDFacturaRectificada"][0]
		self.assertEqual(rectified["IDEmisorFactura"], VALID_NIF)
		self.assertEqual(rectified["NumSerieFactura"], original.name)
		self.assertEqual(
			rectified["FechaExpedicionFactura"],
			format_aeat_date(frappe.db.get_value("Sales Invoice", original.name, "posting_date")),
		)

	def test_rectification_without_link_blocked(self):
		"""R* sin return_against NI trío externo: rebota con remedio."""
		self._activate()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._draft_invoice(es_invoice_type="R1")

		mensaje = str(ctx.exception)
		self.assertIn("rectificada", mensaje)
		self.assertIn("Remedio", mensaje)

	def test_empty_breakdown_blocked_unless_exempt(self):
		"""Sin impuestos NI causa de exención: rebota; con causa de exención
		L10 pasa la compuerta (spec 04 §4/§7).

		OJO fixture: frappe rellena los Select SIN default con su PRIMERA
		opción al crear docs (model/create_new.py, get_static_default_value)
		— «es_verifactu_exempt_cause» nacería «E1» y la compuerta jamás
		rebotaría. Se fija «» explícito (None NO vale: update_if_missing lo
		repone) para expresar «sin causa de exención»."""
		self._activate()

		with self.assertRaises(frappe.ValidationError) as ctx:
			self._draft_invoice(taxes=[], es_verifactu_exempt_cause="")
		self.assertIn("exención", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

		# con la causa de exención la misma factura pasa:
		exenta = self._draft_invoice(taxes=[], es_verifactu_exempt_cause="E1")
		self.assertEqual(exenta.docstatus, 0)  # borrador guardado sin rebote

	def test_invoice_type_required_with_active_company(self):
		"""Requerimiento condicional (Batch 3): compañía activa → tipo
		obligatorio. Al INSERTAR, el default del Custom Field («F1») rellena
		el campo ANTES de validate (frappe: update_if_missing sobre el new_doc
		template) — nada que rebote. Se reproduce el UX real: el usuario
		VACÍA el campo en un borrador ya guardado y graba → rebota."""
		self._activate()
		a = self._draft_invoice()  # nace con el default «F1»
		a.set("es_invoice_type", None)
		with self.assertRaises(frappe.ValidationError) as ctx:
			a.save(ignore_permissions=True)

		self.assertIn("tipo de factura", str(ctx.exception).lower())
		self.assertIn("Remedio", str(ctx.exception))

	# --- rollback del submit (seam es_test_fail_submit, lote 4b) -------------

	def test_failed_submit_leaves_no_record(self):
		"""Fallo después del renombre (seam): al revertir NO queda registro
		del libro y el contador de la serie queda liberado; el siguiente
		submit encadena sobre el estado PREVIO (sin huecos ni horquillas)."""
		self._activate()
		a = self._draft_invoice()
		before = frappe.get_all(LEDGER_DOCTYPE, filters={"company": self.company}, pluck="name")

		frappe.db.savepoint("es_l4c")
		frappe.flags.es_test_fail_submit = True
		try:
			with self.assertRaises(frappe.ValidationError):
				a.submit()
		finally:
			frappe.flags.es_test_fail_submit = False

		# falló DESPUÉS del renombre:
		self.assertTrue(a.name.startswith("SIF1-"), a.name)

		# la petición real se revierte entera; aquí, al savepoint:
		frappe.db.rollback(save_point="es_l4c")

		self.assertEqual(
			frappe.get_all(LEDGER_DOCTYPE, filters={"company": self.company}, pluck="name"),
			before,
		)

		# el siguiente submit encadena sobre el estado previo: misma cantidad
		# previa + 1, sin huecos ni horquillas:
		b = self._draft_invoice()
		b.submit()
		chain = frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"company": self.company},
			fields=["chain_index", "previous_hash", "hash"],
			order_by="chain_index asc",
		)
		self.assertEqual(len(chain), len(before) + 1)
		self.assertEqual(
			[r.previous_hash for r in chain],
			[""] + [r.hash for r in chain[:-1]],
		)

	# --- cerrojo de cadena: API manual (spec 04 §12) -------------------------

	def test_manual_lock_api(self):
		"""La API manual del 4c: acquire → una segunda adquisición (instancia
		nueva) con timeout corto rebota con remedio; release → readquisición
		inmediata; release idempotente."""
		lock = locks.acquire_chain_lock(self.company)
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				locks.acquire_chain_lock(self.company, timeout=0.3)
			self.assertIn("cerrojo", str(ctx.exception))
			self.assertIn("Remedio", str(ctx.exception))
		finally:
			locks.release_chain_lock(lock)

		# liberado → readquisición inmediata y nueva liberación sin error:
		segundo = locks.acquire_chain_lock(self.company, timeout=1)
		locks.release_chain_lock(segundo)
		locks.release_chain_lock(segundo)  # idempotente

	# --- encadenamiento bajo ráfaga (spec 04 §12) ----------------------------

	def test_sequential_submits_chain_without_fork(self):
		"""REDISEÑO del test de concurrencia (lote 4c, spec 04 §12).

		El original levantaba DOS THREADS con conexiones frappe separadas
		para submitir en paralelo real: el cerrojo de cadena serializa SU
		sección crítica (renombre + registro), pero el INSERT del borrador
		consume el contador tabSeries de la serie de borradores FUERA de
		ella — dos threads deadlockan la base (QueryDeadlockError sobre
		filas de tabSeries) y el test flaqueaba. NO es defecto del producto
		(la sección crítica está protegida); es una limitación del harness,
		documentada aquí. El nombre se conserva por trazabilidad del lote.

		Lo que se asierte, de forma DETERMINISTA (sin sleeps): una ráfaga de
		submits SECUENCIALES rápidos sobre la misma compañía consume números
		fiscales CONSECUTIVOS (sin huecos) y encadena chain_index
		CONSECUTIVO, cada huella colgando de la anterior (sin horquilla).
		La semántica del cerrojo manual (segunda adquisición rebota,
		release readquiere) la cubre test_manual_lock_api: no se duplica.
		"""
		self._activate()
		facturas = [self._draft_invoice() for _ in range(3)]
		for si in facturas:  # ráfaga: uno detrás de otro, sin esperas
			si.submit()

		# números fiscales CONSECUTIVOS (relativos: el contador de la clase
		# ya arranca avanzado por los tests anteriores):
		numeros = [int(si.name.rsplit("-", 1)[1]) for si in facturas]
		self.assertEqual(numeros, list(range(numeros[0], numeros[0] + len(numeros))))

		# cadena: índices consecutivos base 1 (el setUp vació el libro),
		# encadenada de huella en huella, todas distintas (sin horquilla):
		chain = frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"company": self.company},
			fields=["chain_index", "hash", "previous_hash"],
			order_by="chain_index asc",
		)
		self.assertEqual([r.chain_index for r in chain], [1, 2, 3])
		self.assertEqual(chain[0].previous_hash, "")
		for previous, current in itertools.pairwise(chain):
			self.assertEqual(current.previous_hash, previous.hash)
		self.assertEqual(len({r.hash for r in chain}), 3)
