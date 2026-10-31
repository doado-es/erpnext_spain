# FLUJO DE INTEGRACIÓN COMPLETO VeriFactu — lote 6b, la PRUEBA DE ACEPTACIÓN
# del spec 04 (§14 «Workflow de integración»):
#
#     emisión → remisión (cliente mockeado) → respuesta correcta →
#     respuesta errónea → subsanación → anulación → consulta AEAT →
#     integridad de la cadena completa.
#
# UN solo test: el ciclo de vida entero de DOS facturas sobre el MISMO
# libro, en orden, en una transacción — la cadena que deja el flujo es la
# que se verifica eslabón por eslabón al final (PASO 7). Cada paso
# orquesta las piezas ya cubiertas por sus lotes (test_emision_registros /
# test_remision / test_rectification): lo que aquí se prueba es que FUNCIONAN
# JUNTAS y en el orden legal del workflow.
#
# Misma NOTA de colocación que test_remision.py: módulo en tests/, sin
# IGNORE_TEST_RECORD_DEPENDENCIES (raise NotImplementedError fuera de
# carpeta de doctype). Masters reales del site; rollback POR CLASE (un
# solo test: el setUp devuelve la compañía a estado prístino por si la
# clase corrida antes dejó restos). El rate-limit del manager vive en
# Redis (fuera de la transacción): el helper de drenaje lo limpia ANTES de
# cada remisión — cada PASO es «la próxima corrida del scheduler», con la
# espera de 60 s de la remisión anterior ya transcurrida.

from __future__ import annotations

import glob
import json
import os
import unittest.mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from erpnext_spain.aeat.client import AEATClient
from erpnext_spain.aeat.manager import AEATOutboxManager
from erpnext_spain.aeat.tests.helpers import (
	clean_pem,
	generate_p12,
	test_company,
	write_private_p12,
)
from erpnext_spain.aeat.tests.mock_aeat_client import (
	MockAEATClient,
	load_seed,
	mock_client_factory,
)
from erpnext_spain.aeat.utils import absolute_site_path, format_aeat_date, format_aeat_datetime
from erpnext_spain.es_verifactu import emission, rectification
from erpnext_spain.es_verifactu.doctype.es_verifactu_aeat_query.es_verifactu_aeat_query import (
	query_aeat,
)
from erpnext_spain.es_verifactu.driver import VerifactuDriver
from erpnext_spain.tests.fixtures import TEST_CUSTOMER, TEST_ITEM

P12_PATTERN = "es_test_flujo_*.p12"
PASSWORD = "es-test-pass"

VALID_NIF = "12345678Z"
ACTIVATION_DATE = "2026-01-01"

DRAFT_SERIES = "BORRADOR-.#####"
F1_SERIES = "SIF1-.####."
R1_SERIES = "RC-.####."

CUSTOMER = TEST_CUSTOMER
ITEM = TEST_ITEM

LEDGER_DOCTYPE = "ES Verifactu Billing Record"
QUERY_DOCTYPE = "ES Verifactu Aeat Query"

OPERATION = "RegFactuSistemaFacturacion"
QUERY_OPERATION = "ConsultaFactuSistemaFacturacion"

# Código de subsanación MANUAL de la AEAT (errores.properties): la cura es
# humana — nada se reemite automáticamente (lote 5b).
MANUAL_RECTIFICATION_CODE = 3000
DESC_DUPLICADO = "Registro de facturación duplicado."

NOTIFIER_ROLE = "ES VeriFactu Notificador Flujo"
NOTIFIED_USER = "es_notifica_flujo@test.example.com"
UNAUTHORIZED_USER = "es_sin_permiso_flujo@test.example.com"
INCIDENTS_EMAIL = "asesor@test.example.com"


def _delete_test_p12() -> None:
	for path in glob.glob(absolute_site_path("private", "files", P12_PATTERN)):
		os.remove(path)


def _ensure_users() -> None:
	"""Rol + usuarios de los tests: el notificado (canal in-app de las
	incidencias — notify_roles salta la auto-notificación del propio
	Administrador) y el usuario SIN permiso AEAT (gate de la consulta)."""
	if not frappe.db.exists("Role", NOTIFIER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": NOTIFIER_ROLE}).insert(
			ignore_permissions=True
		)
	if not frappe.db.exists("User", NOTIFIED_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": NOTIFIED_USER,
				"first_name": "ES",
				"last_name": "Notifica Flujo",
				"roles": [{"role": NOTIFIER_ROLE}],
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("User", UNAUTHORIZED_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": UNAUTHORIZED_USER,
				"first_name": "ES",
				"last_name": "Sin Permiso Flujo",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)


class TestCompleteVerifactuWorkflow(IntegrationTestCase):
	"""La prueba de aceptación del spec 04 (§14): el workflow de integración
	completo — emisión → remisión → respuesta correcta → respuesta errónea →
	subsanación → anulación → consulta → cadena íntegra."""

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
		_ensure_users()

	def setUp(self):
		frappe.set_user("Administrator")
		# Un solo test, pero el reset guarda contra restos de corridas
		# abortadas: compañía prístina, sin libro, sin consultas, sin
		# credenciales. El rate-limit (Redis) se limpia en el helper de
		# drenaje antes de CADA remisión del flujo.
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
				"es_verifactu_mandatory_in_order_cure": 0,
				"es_incidents_email": None,
				"tax_id": None,
			},
		)
		frappe.db.delete("ES Invoice Series", {"parent": self.company})
		frappe.db.delete("ES Verifactu Notification Role", {"parent": self.company})
		frappe.db.delete(LEDGER_DOCTYPE, {"company": self.company})
		frappe.db.delete(QUERY_DOCTYPE, {"company": self.company})
		for credential in frappe.get_all("ES AEAT Credential", filters={"company": self.company}, pluck="name"):
			frappe.delete_doc("ES AEAT Credential", credential, ignore_permissions=True)

	# --- helpers de fixture (patrón de test_rectification.py) ----------------

	def _activate(self, notify: bool = False):
		"""Deja la compañía ACTIVA (compuerta completa) con credencial y
		mapeo serie↔tipo F1/R1; con `notify`, también su rol de
		notificación de incidencias (canal in-app de los tests)."""
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
		doc.es_verifactu_test_mode = "Pruebas"
		doc.es_draft_series = DRAFT_SERIES
		doc.es_verifactu_remission_mode = "Diferida"
		doc.set("es_invoice_series", [])
		doc.append("es_invoice_series", {"series": F1_SERIES, "invoice_type": "F1"})
		doc.append("es_invoice_series", {"series": R1_SERIES, "invoice_type": "R1"})
		doc.set("es_verifactu_notification_roles", [])
		if notify:
			doc.append("es_verifactu_notification_roles", {"role": NOTIFIER_ROLE})
		url = write_private_p12(
			f"es_test_flujo_{frappe.generate_hash(length=8)}.p12", self.p12
		)
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
		return frappe.get_doc(data).insert(ignore_permissions=True)

	def _register_in_chain(self):
		"""Registros del libro de la empresa (cadena completa) ordenados."""
		return frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"company": self.company},
			fields=[
				"name",
				"sales_invoice",
				"record_type",
				"chain_index",
				"hash",
				"previous_hash",
				"record_json",
				"status",
				"curable",
			],
			order_by="chain_index asc",
		)

	def _adapted_seed(self, lines: list[tuple[str, str, str, object, str | None]]) -> dict:
		"""Carga la SEMILLA REAL de respuesta AEAT y adapta sus
		RespuestaLinea a nuestros registros (misma forma de línea,
		RefExterna → docname del registro del libro).

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
		reproduce `response` para la operación de remisión.

		El rate-limit del manager (Redis) se limpia ANTES: cada remisión del
		flujo es la «próxima corrida del scheduler» — la espera de 60 s que
		pidió la AEAT en la remisión anterior ya transcurrió.

		ACOTADO a la compañía de prueba (drain_company): el site puede tener
		otras empresas con pendientes REALES (registro en vivo del entorno
		de pruebas) que un drain global remitiría por el mock."""
		frappe.cache().delete_keys("es_aeat_rate_limit:*")
		mock = MockAEATClient(responses={OPERATION: response})
		AEATOutboxManager().drain_company(
			VerifactuDriver(client_factory=lambda **kw: mock), self.company
		)
		return mock

	def _in_app_alerts(self) -> list[str]:
		"""Asuntos de Notification Log de la compañía para el usuario del rol
		de notificación (canal in-app, spec 04 §9)."""
		return frappe.get_all(
			"Notification Log",
			filters={
				"for_user": NOTIFIED_USER,
				"document_type": "Company",
				"document_name": self.company,
			},
			pluck="subject",
		)

	# --- el workflow (spec 04 §14) -------------------------------------------

	def test_complete_flow_issuance_to_query(self):
		"""Emisión → remisión → correcta → errónea → subsanación →
		anulación → consulta AEAT → cadena íntegra: la aceptación del spec 04."""
		# --------------------------------------------------------------------
		# PASO 0 — Compañía ACTIVA (compuerta completa): credencial habilitada,
		# series F1/R1 y los DOS canales de incidencias (rol in-app + email
		# del asesor fiscal).
		# --------------------------------------------------------------------
		self._activate(notify=True)
		frappe.db.set_value("Company", self.company, "es_incidents_email", INCIDENTS_EMAIL)

		# --------------------------------------------------------------------
		# PASO 1 — EMISIÓN (lote 4): submit de la factura A → renombre quirúrgico
		# a la serie fiscal + RegistroAlta encadenado (huella) + estado
		# denormalizado de la factura.
		# --------------------------------------------------------------------
		a = self._draft()
		a.submit()

		# el borrador se renombró al número fiscal de la serie mapeada (SIF1)
		self.assertTrue(a.name.startswith("SIF1"), a.name)

		records = self._register_in_chain()
		self.assertEqual(len(records), 1)
		issuance_a = records[0]
		self.assertEqual(issuance_a.record_type, "RegistroAlta")
		self.assertEqual(issuance_a.chain_index, 1)  # PrimerRegistro de la cadena
		self.assertEqual(json.loads(issuance_a.record_json)["PrimerRegistro"], "S")
		self.assertEqual(issuance_a.previous_hash, "")
		self.assertTrue(issuance_a.hash)  # huella calculada sobre el record_json
		self.assertEqual(issuance_a.status, "PendienteEnvio")  # nace en el outbox
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_PENDING_SEND,
		)

		# --------------------------------------------------------------------
		# PASO 2 — REMISIÓN con respuesta CORRECTA (lote 5a): el drenaje remite
		# el Alta de A a la AEAT (mock) y la acepta → registro Correcto +
		# factura «Alta Aceptada» (mapper de emission.py).
		# --------------------------------------------------------------------
		self._drain_with_mock(
			self._adapted_seed([(issuance_a.name, a.name, "Correcto", None, None)])
		)

		self.assertEqual(frappe.db.get_value(LEDGER_DOCTYPE, issuance_a.name, "status"), "Correcto")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_ISSUANCE_ACCEPTED,
		)

		# --------------------------------------------------------------------
		# PASO 3 — RESPUESTA ERRÓNEA (lote 5b): la factura B se emite y la AEAT
		# (mock) la RECHAZA con un código de subsanación manual (3000:
		# duplicado) → registro Incorrecto + subsanable + incidencia por los
		# DOS canales de la compañía.
		# --------------------------------------------------------------------
		b = self._draft()
		b.submit()
		issuance_b = self._register_in_chain()[1]
		self.assertEqual(issuance_b.chain_index, 2)  # encadena sobre el Alta de A

		with unittest.mock.patch("frappe.sendmail") as sendmail:
			self._drain_with_mock(
				self._adapted_seed(
					[(issuance_b.name, b.name, "Incorrecto", MANUAL_RECTIFICATION_CODE, DESC_DUPLICADO)]
				)
			)

		# el registro queda Incorrecto + marcado Subsanable (la cura es humana)
		record_b = frappe.get_doc(LEDGER_DOCTYPE, issuance_b.name)
		self.assertEqual(record_b.status, "Incorrecto")
		self.assertEqual(record_b.response_error_code, str(MANUAL_RECTIFICATION_CODE))
		self.assertEqual(record_b.curable, 1)
		# el 3000 es subsanación MANUAL: nada se reemitió automáticamente
		self.assertEqual(len(self._register_in_chain()), 2)

		# canal EMAIL (es_incidents_email de la compañía)
		self.assertEqual(sendmail.call_args.kwargs["recipients"], [INCIDENTS_EMAIL])
		self.assertIn("requiere subsanación manual", sendmail.call_args.kwargs["subject"])
		# canal IN-APP (Notification Log del rol notificador)
		alerts = self._in_app_alerts()
		self.assertTrue(
			any(
				"requiere subsanación manual" in subject and b.name in subject
				for subject in alerts
			),
			alerts,
		)

		# la factura B refleja el error SIN estado terminal del mapper (su
		# Alta fue rechazada): sigue «Pendiente Envío» — la corrección es la
		# subsanación, no un estado de la factura
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", b.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_PENDING_SEND,
		)

		# --------------------------------------------------------------------
		# PASO 4 — SUBSANACIÓN (lote 5b): rectify B regenera su Alta desde el
		# estado ACTUAL con los indicadores Subsanación + RechazoPrevio,
		# encadenada sobre el ÚLTIMO registro del SIF; la AEAT (mock) la acepta
		# → factura «Alta Aceptada». (SinRegistroPrevio NO viaja en el Alta:
		# es campo del tipo anulación del WSDL, verificado en vivo.)
		# --------------------------------------------------------------------
		new_b = rectification.rectify(b.name)

		rectified_b = frappe.get_doc(LEDGER_DOCTYPE, new_b)
		self.assertEqual(rectified_b.record_type, "RegistroAlta")
		self.assertEqual(rectified_b.status, "PendienteEnvio")  # vuelve al outbox
		self.assertEqual(rectified_b.is_correction, 1)
		self.assertEqual(rectified_b.prior_rejection, 1)  # su alta previa fue rechazada
		self.assertEqual(rectified_b.no_prior_record, 0)  # campo de anulación: nunca en el Alta
		self.assertEqual(rectified_b.chain_index, 3)
		self.assertEqual(rectified_b.previous_hash, issuance_b.hash)  # sobre el ÚLTIMO

		# el registro original queda congelado (libro inmutable) y fuera de lo
		# subsanable
		self.assertEqual(frappe.db.get_value(LEDGER_DOCTYPE, issuance_b.name, "status"), "Incorrecto")
		self.assertEqual(frappe.db.get_value(LEDGER_DOCTYPE, issuance_b.name, "curable"), 0)

		self._drain_with_mock(
			self._adapted_seed([(new_b, b.name, "Correcto", None, None)])
		)
		self.assertEqual(frappe.db.get_value(LEDGER_DOCTYPE, new_b, "status"), "Correcto")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", b.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_ISSUANCE_ACCEPTED,
		)

		# --------------------------------------------------------------------
		# PASO 5 — ANULACIÓN (lote 4c + 5a): cancelar A genera su
		# RegistroAnulación encadenado; el drenaje remite su wire y la AEAT
		# (mock) lo acepta → registro Correcto + factura «Anulada».
		# --------------------------------------------------------------------
		a = frappe.get_doc("Sales Invoice", a.name)
		a.cancel()

		cancellation_a = next(
			r for r in self._register_in_chain() if r.record_type == "RegistroAnulacion"
		)
		self.assertEqual(cancellation_a.status, "PendienteEnvio")
		# la anulación ENCADENA sobre el último registro del SIF (la
		# subsanación de B, no el Alta de A)
		self.assertEqual(cancellation_a.chain_index, 4)
		self.assertEqual(cancellation_a.previous_hash, rectified_b.hash)

		cancellation_response = self._adapted_seed(
			[(cancellation_a.name, a.name, "Correcto", None, None)]
		)
		cancellation_response["RespuestaLinea"][0]["Operacion"]["TipoOperacion"] = "Anulacion"
		self._drain_with_mock(cancellation_response)

		self.assertEqual(frappe.db.get_value(LEDGER_DOCTYPE, cancellation_a.name, "status"), "Correcto")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_CANCELLED,
		)

		# --------------------------------------------------------------------
		# PASO 6 — CONSULTA a la AEAT (lote 6b): «ES Verifactu Aeat Query»
		# pregunta por los registros del período y persiste el crudo + una
		# fila por registro devuelto. El cliente va mockeado con la factory de
		# tests (comportamiento por operación que además CAPTURA el wire) —
		# todo el camino de producción del AEATClient menos la TLS.
		# --------------------------------------------------------------------
		credential = frappe.get_all(
			"ES AEAT Credential",
			filters={"company": self.company, "purpose": "VeriFactu", "enabled": 1},
			pluck="name",
		)[0]
		# la ficha de la compañía referencia su credencial: el doctype la toma
		# por DEFAULT del campo es_verifactu_credential (la UI hace el fetch)
		frappe.db.set_value("Company", self.company, "es_verifactu_credential", credential)

		query = frappe.get_doc(
			{
				"doctype": QUERY_DOCTYPE,
				"company": self.company,
				"from_date": frappe.utils.today(),  # rango del período corriente
				"to_date": frappe.utils.today(),
			}
		).insert(ignore_permissions=True)
		self.assertEqual(query.credential, credential)  # default aplicado

		# GATE de permiso explícito (doc 12 §18): sin permiso AEAT sobre LA
		# EMPRESA no hay consulta (fix del v1: nada implícito del site)
		frappe.set_user(UNAUTHORIZED_USER)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			query_aeat(query.name)
		frappe.set_user("Administrator")

		# respuesta de la consulta (forma RespuestaConsultaLR.xsd): la AEAT
		# devuelve el estado CONSOLIDADO de cada factura del período — A
		# (anulada) y B (su subsanación aceptada, con los indicadores)
		aeat_date = format_aeat_date(a.posting_date)
		period = frappe.utils.getdate(frappe.utils.today())
		query_response = {
			"Cabecera": {
				"IDVersion": "1.0",
				"ObligadoEmision": {
					"NombreRazon": frappe.db.get_value("Company", self.company, "company_name"),
					"NIF": VALID_NIF,
				},
			},
			"PeriodoImputacion": {
				"Ejercicio": str(period.year),
				"Periodo": f"{period.month:02d}",
			},
			"IndicadorPaginacion": "N",
			"ResultadoConsulta": "ConDatos",
			"RegistroRespuestaConsultaFactuSistemaFacturacion": [
				{
					"IDFactura": {
						"IDEmisorFactura": VALID_NIF,
						"NumSerieFactura": a.name,
						"FechaExpedicionFactura": aeat_date,
					},
					"DatosRegistroFacturacion": {"TipoFactura": "F1", "ImporteTotal": "121.00"},
					"EstadoRegistro": {
						"TimestampUltimaModificacion": format_aeat_datetime(),
						"EstadoRegistro": "Anulado",
					},
				},
				{
					"IDFactura": {
						"IDEmisorFactura": VALID_NIF,
						"NumSerieFactura": b.name,
						"FechaExpedicionFactura": aeat_date,
					},
					"DatosRegistroFacturacion": {
						"TipoFactura": "F1",
						"Subsanacion": "S",
						"RechazoPrevio": "S",
						"ImporteTotal": "121.00",
					},
					"EstadoRegistro": {
						"TimestampUltimaModificacion": format_aeat_datetime(),
						"EstadoRegistro": "Correcto",
					},
				},
			],
		}

		wire: dict = {}

		def behavior(data: dict) -> dict:
			"""Comportamiento de la operación de consulta: captura el
			Cabecera/FiltroConsulta remitidos y reproduce la respuesta."""
			wire.update(data)
			return query_response

		def factory(**kwargs):
			"""Factory del cliente de la consulta: AEATClient REAL con el zeep
			mockeado (mock_client_factory) — se recorre TODO el camino de
			producción del cliente menos la TLS."""
			return AEATClient(
				client_factory=mock_client_factory({QUERY_OPERATION: behavior}),
				**kwargs,
			)

		with unittest.mock.patch(
			"erpnext_spain.es_verifactu.doctype.es_verifactu_aeat_query.es_verifactu_aeat_query.build_client",
			new=factory,
		):
			result = query_aeat(query.name)

		# la respuesta cruda vuelve al llamador
		self.assertEqual(result["ResultadoConsulta"], "ConDatos")

		# el WIRE de la consulta (forma de la referencia): CabeceraConsultaSf
		# con IDVersion + obligado, y el filtro con el período derivado del
		# rango + el rango de fechas de expedición
		self.assertEqual(
			wire["Cabecera"],
			{
				"IDVersion": "1.0",
				"ObligadoEmision": {
					"NombreRazon": frappe.db.get_value("Company", self.company, "company_name"),
					"NIF": VALID_NIF,
				},
			},
		)
		self.assertEqual(
			wire["FiltroConsulta"],
			{
				"PeriodoImputacion": {
					"Ejercicio": str(period.year),
					"Periodo": f"{period.month:02d}",
				},
				"FechaExpedicionFactura": {
					"RangoFechaExpedicion": {"Desde": aeat_date, "Hasta": aeat_date}
				},
			},
		)

		# persistencia: crudo (resultado) + una fila por registro devuelto
		query = frappe.get_doc(QUERY_DOCTYPE, query.name)
		self.assertEqual(json.loads(query.result)["ResultadoConsulta"], "ConDatos")
		lines = query.lines
		self.assertEqual([line.state for line in lines], ["Anulado", "Correcto"])
		id_a = json.loads(lines[0].invoice_id)
		self.assertEqual(id_a["NumSerieFactura"], a.name)  # A: anulada ante la AEAT
		id_b = json.loads(lines[1].invoice_id)
		self.assertEqual(id_b["NumSerieFactura"], b.name)  # B: subsanación aceptada
		data_b = json.loads(lines[1].record_data)
		self.assertEqual(data_b["Subsanacion"], "S")
		self.assertEqual(data_b["RechazoPrevio"], "S")

		# --------------------------------------------------------------------
		# PASO 7 — INTEGRIDAD DE LA CADENA COMPLETA (spec 04 §2.2/§5): el
		# flujo dejó 4 registros (A alta, B alta rechazada, B subsanación, A
		# anulación): chain_index consecutivo base 1 y cada previous_huella =
		# la huella de su predecesor — eslabón por eslabón, sin horquillas.
		# --------------------------------------------------------------------
		chain = self._register_in_chain()
		self.assertEqual([r.chain_index for r in chain], [1, 2, 3, 4])
		self.assertEqual(
			[r.record_type for r in chain],
			["RegistroAlta", "RegistroAlta", "RegistroAlta", "RegistroAnulacion"],
		)
		self.assertEqual(
			[r.status for r in chain],
			["Correcto", "Incorrecto", "Correcto", "Correcto"],
		)
		self.assertTrue(all(r.hash for r in chain))
		# el primero es el PrimerRegistro de la cadena (sin predecesor)
		self.assertEqual(chain[0].previous_hash, "")
		self.assertEqual(json.loads(chain[0].record_json)["PrimerRegistro"], "S")
		# cada registro encadena sobre la huella del anterior (sin huecos)
		for previous, current in zip(chain, chain[1:]):
			self.assertEqual(
				current.previous_hash,
				previous.hash,
				f"{current.name} (cadena {current.chain_index}) no encadena sobre"
				f" {previous.name} (cadena {previous.chain_index})",
			)
