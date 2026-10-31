# Tests del lote 5b (spec 04 §3/§9): ESTRATEGIA por código de error AEAT
# (reintento / subsanación automática / manual / desconocido — post-proceso
# del driver 5a), SUBSANACIÓN manual whitelisted (regeneración del Alta
# desde el estado actual de la factura, encadenada sobre el ÚLTIMO registro
# del SIF, indicadores Subsanación/RechazoPrevio/SinRegistroPrevio),
# subsanación EN ORDEN (mandatory_in_order_cure), permiso explícito doc 12
# §18, report «Rectifiable Invoices» y alerta diaria de outbox ESTANCADO
# (spec 04 §8).
#
# Misma NOTA de colocación que test_remision.py: módulo en tests/, sin
# IGNORE_TEST_RECORD_DEPENDENCIES (raise NotImplementedError fuera de
# carpeta de doctype). Masters reales del site; rollback POR CLASE (el
# setUp devuelve la compañía a estado prístino y borra sus registros del
# libro por db.delete). Rate-limit del manager en Redis: se limpia en el
# setUp para que cada drain arranque habilitado.

from __future__ import annotations

import glob
import json
import os
import unittest.mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from erpnext_spain.aeat.manager import AEATOutboxManager
from erpnext_spain.aeat.tests.helpers import (
	clean_pem,
	generate_p12,
	test_company,
	write_private_p12,
)
from erpnext_spain.aeat.tests.mock_aeat_client import MockAEATClient, load_seed
from erpnext_spain.aeat.utils import absolute_site_path
from erpnext_spain.es_verifactu import emission, error_strategy, rectification, tasks
from erpnext_spain.es_verifactu.driver import VerifactuDriver
from erpnext_spain.es_verifactu.report.rectifiable_invoices import (
	rectifiable_invoices as report,
)
from erpnext_spain.tests.fixtures import TEST_CUSTOMER, TEST_ITEM

P12_PATTERN = "es_test_rectification_*.p12"
PASSWORD = "es-test-pass"

VALID_NIF = "12345678Z"
ACTIVATION_DATE = "2026-01-01"

DRAFT_SERIES = "BORRADOR-.#####"
F1_SERIES = "SIF1-.####."
R1_SERIES = "RC-.####."

CUSTOMER = TEST_CUSTOMER
ITEM = TEST_ITEM

LEDGER_DOCTYPE = "ES Verifactu Billing Record"
RESPONSE_DOCTYPE = "ES AEAT Response"

OPERATION = "RegFactuSistemaFacturacion"

DESC_DUPLICADO = "Registro de facturación duplicado."

NOTIFIER_ROLE = "ES VeriFactu Notificador Subsanacion"
NOTIFIED_USER = "es_notifica_subsanacion@test.example.com"
UNAUTHORIZED_USER = "es_sin_permiso_subsanacion@test.example.com"
AUTHORIZED_USER = "es_con_permiso_subsanacion@test.example.com"


def _delete_test_p12() -> None:
	for path in glob.glob(absolute_site_path("private", "files", P12_PATTERN)):
		os.remove(path)


def _ensure_notified_user() -> None:
	"""Crea (idempotente) el rol y el usuario que reciben las incidencias
	in-app en los tests: notify_roles salta la auto-notificación del propio
	Administrador (for_user == from_user), así que las incidencias de los
	dos canales se afirman sobre este usuario."""
	if not frappe.db.exists("Role", NOTIFIER_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": NOTIFIER_ROLE}).insert(ignore_permissions=True)
	if not frappe.db.exists("User", NOTIFIED_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": NOTIFIED_USER,
				"first_name": "ES",
				"last_name": "Notifica Subsanacion",
				"roles": [{"role": NOTIFIER_ROLE}],
				"enabled": 1,
			}
		).insert(ignore_permissions=True)


class BaseRectification(IntegrationTestCase):
	"""Fixture compartida del lote 5b (patrón de test_remision.py)."""

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
				"es_verifactu_mandatory_in_order_cure": 0,
				"es_incidents_email": None,
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

	# --- helpers de fixture (patrón de test_remision.py) --------------------

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
		url = write_private_p12(f"es_test_rectification_{frappe.generate_hash(length=8)}.p12", self.p12)
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
				"status",
				"response_error_code",
				"curable",
				"is_correction",
				"prior_rejection",
				"no_prior_record",
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

		ACOTADO a la compañía de prueba (drain_company): el site puede tener
		otras empresas con pendientes REALES (registro en vivo del entorno
		de pruebas) que un drain global remitiría por el mock."""
		mock = MockAEATClient(responses={OPERATION: response})
		AEATOutboxManager().drain_company(VerifactuDriver(client_factory=lambda **kw: mock), self.company)
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


class TestErrorStrategy(BaseRectification):
	"""Estrategia por código de error (spec 04 §3): el mapa y el efecto de
	cada clase sobre el libro + las notificaciones."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_notified_user()

	def test_strategy_map(self):
		"""Clasificación pura del mapa (semillas de la referencia): un código
		representante por clase + degradación a desconocido."""
		self.assertEqual(error_strategy.strategy_for(4108), error_strategy.STRATEGY_RETRY)
		self.assertEqual(error_strategy.strategy_for(2004), error_strategy.STRATEGY_AUTO_RECTIFICATION)
		self.assertEqual(error_strategy.strategy_for(3000), error_strategy.STRATEGY_MANUAL_RECTIFICATION)
		self.assertEqual(error_strategy.strategy_for("12345"), error_strategy.STRATEGY_UNKNOWN)
		self.assertEqual(error_strategy.strategy_for(None), error_strategy.STRATEGY_UNKNOWN)
		self.assertTrue(error_strategy.is_curable(3000))
		self.assertFalse(error_strategy.is_curable(2004))

	def test_retry_resubmits_issuance_with_prior_rejection(self):
		"""Código 4108 (transitorio) + Incorrecto → registro NUEVO encadenado
		con flag prior_rejection que reenvía el Alta de la MISMA factura; el
		original queda congelado Incorrecto y la factura sigue en el outbox
		(Pendiente Envío)."""
		self._activate()
		a = self._draft()
		a.submit()
		original = self._register_in_chain()[0]
		self._drain_with_mock(
			self._adapted_seed([(original.name, a.name, "Incorrecto", 4108, "Error transitorio de la AEAT.")])
		)

		rows = self._register_in_chain()
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0].status, "Incorrecto")
		self.assertEqual(rows[0].response_error_code, "4108")

		retry = rows[1]
		self.assertEqual(retry.sales_invoice, a.name)
		self.assertEqual(retry.record_type, "RegistroAlta")
		self.assertEqual(retry.status, "PendienteEnvio")
		self.assertEqual(retry.prior_rejection, 1)
		self.assertEqual(retry.is_correction, 0)
		self.assertEqual(retry.chain_index, 2)
		self.assertEqual(retry.previous_hash, rows[0].hash)  # encadena sobre el ÚLTIMO

		# flags REALES del wire (fix del drenaje en vivo): la reemisión ya
		# tiene un alta remitida (Subsanacion "S") y el rechazo NO está en
		# la AEAT (RechazoPrevio "X"). SinRegistroPrevio NO viaja en el Alta.
		data = json.loads(frappe.db.get_value(LEDGER_DOCTYPE, retry.name, "record_json"))
		self.assertEqual(data["Subsanacion"], "S")
		self.assertEqual(data["RechazoPrevio"], "X")
		self.assertNotIn("SinRegistroPrevio", data)  # campo del tipo anulación

		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_PENDING_SEND,
		)

	def test_auto_rectification_regenerates_with_flag(self):
		"""Código 2004 (timestamp fuera de rango) con AceptadoConErrores →
		regeneración SIN intervención: registro NUEVO con flag is_correction
		(timestamp fresco de now_aeat); el original queda aceptado-con-errores
		y la factura conserva su estado denormalizado (la subsanación
		automática no la toca: sigue pendiente de la respuesta del registro
		nuevo)."""
		self._activate()
		a = self._draft()
		a.submit()
		original = self._register_in_chain()[0]
		self._drain_with_mock(
			self._adapted_seed(
				[
					(
						original.name,
						a.name,
						"AceptadoConErrores",
						2004,
						"El valor del campo FechaHoraHusoGenRegistro debe ser la fecha actual del sistema de la AEAT.",
					)
				]
			)
		)

		rows = self._register_in_chain()
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0].status, "AceptadoConErrores")

		auto_rectification = rows[1]
		self.assertEqual(auto_rectification.sales_invoice, a.name)
		self.assertEqual(auto_rectification.status, "PendienteEnvio")
		self.assertEqual(auto_rectification.is_correction, 1)
		self.assertEqual(auto_rectification.prior_rejection, 0)  # no fue rechazo: fue aceptación con errores
		self.assertEqual(auto_rectification.previous_hash, rows[0].hash)

		# flags REALES del wire: reemisión (Subsanacion "S") tras una
		# ACEPTACIÓN con errores — no hubo rechazo (RechazoPrevio "N").
		data = json.loads(frappe.db.get_value(LEDGER_DOCTYPE, auto_rectification.name, "record_json"))
		self.assertEqual(data["Subsanacion"], "S")
		self.assertEqual(data["RechazoPrevio"], "N")
		self.assertNotIn("SinRegistroPrevio", data)  # campo del tipo anulación

		# la factura conserva el estado del mapper (regresión del lote 5a)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_ISSUANCE_WITH_ERRORS,
		)

	def test_manual_rectification_sets_flag_and_notifies(self):
		"""Código 3000 (duplicado) + Incorrecto → estrategia MANUAL: flag
		«Subsanable» derivado en el registro, SIN reemisión automática, e
		incidencia por el canal in-app (Notification Log) con el remedio y el
		informe donde verla."""
		self._activate(notify=True)
		a = self._draft()
		a.submit()
		original = self._register_in_chain()[0]
		self._drain_with_mock(
			self._adapted_seed([(original.name, a.name, "Incorrecto", 3000, DESC_DUPLICADO)])
		)

		rows = self._register_in_chain()
		self.assertEqual(len(rows), 1)  # nada se reemite: la corrección es humana
		record = frappe.get_doc(LEDGER_DOCTYPE, original.name)
		self.assertEqual(record.status, "Incorrecto")
		self.assertEqual(record.curable, 1)

		alerts = self._in_app_alerts()
		self.assertTrue(
			any(a.name in subject and "requiere subsanación manual" in subject for subject in alerts),
			alerts,
		)
		# el remedio nombra el informe donde verla
		notifications = frappe.get_all(
			"Notification Log",
			filters={"for_user": NOTIFIED_USER, "document_name": self.company},
			fields=["subject", "email_content"],
		)
		content = next(
			n.email_content
			for n in notifications
			if "requiere subsanación manual" in n.subject and a.name in n.subject
		)
		self.assertIn("Rectifiable Invoices", content)

	def test_unknown_logs_and_notifies(self):
		"""Código fuera del mapa (9999) → constancia en Error Log (contactar
		con desarrollo) + incidencia por el canal in-app."""
		self._activate(notify=True)
		a = self._draft()
		a.submit()
		original = self._register_in_chain()[0]
		self._drain_with_mock(
			self._adapted_seed([(original.name, a.name, "Incorrecto", 9999, "Código de error raro.")])
		)

		record = frappe.get_doc(LEDGER_DOCTYPE, original.name)
		self.assertEqual(record.status, "Incorrecto")
		self.assertEqual(record.curable, 0)  # desconocido ≠ subsanable: primero clasifica desarrollo
		self.assertEqual(len(self._register_in_chain()), 1)

		self.assertTrue(
			frappe.get_all(
				"Error Log",
				filters={"method": "VeriFactu: código de error AEAT no contemplado (9999)"},
				pluck="name",
			),
			"se esperaba log_error del código no contemplado",
		)
		alerts = self._in_app_alerts()
		self.assertTrue(any("error desconocido" in subject for subject in alerts), alerts)

	def test_get_dialog_fields_by_code(self):
		"""Whitelisted get_dialog_fields: campos del dialog por código
		(patrón VERIFACTU_ERROR_FIELDS de la referencia), default para
		códigos sin entrada, y copia defensiva (no envenena el mapa)."""
		self._activate()
		fields_3000 = rectification.get_dialog_fields("3000")
		self.assertTrue(
			any(c.get("fieldtype") == "HTML" and "3000" in (c.get("options") or "") for c in fields_3000)
		)
		default_fields = rectification.get_dialog_fields("9999")
		self.assertTrue(any(c.get("fieldname") == "error_code" for c in default_fields))
		default_fields.append({"fieldtype": "Data", "fieldname": "veneno"})
		self.assertNotIn(
			"veneno",
			[c.get("fieldname") for c in rectification.get_dialog_fields("9999")],
		)


class TestManualRectification(BaseRectification):
	"""Flujo manual completo (spec 04 §9): rectify regenera el Alta desde
	el estado ACTUAL, encadena sobre el ÚLTIMO registro del SIF y devuelve
	la factura al outbox."""

	def test_rectify_regenerates_chains_and_returns_to_outbox(self):
		self._activate()
		a, b = self._draft(), self._draft()
		a.submit()
		b.submit()
		rows = self._register_in_chain()
		self._drain_with_mock(
			self._adapted_seed(
				[
					(rows[0].name, a.name, "Incorrecto", 3000, DESC_DUPLICADO),
					(rows[1].name, b.name, "Incorrecto", 3000, DESC_DUPLICADO),
				]
			)
		)

		# el humano corrige la factura (el dato subsanado ya vive en ella)
		frappe.db.set_value("Sales Invoice", a.name, "tax_id", "87654321Z", update_modified=False)

		new_name = rectification.rectify(a.name)
		doc = frappe.get_doc(LEDGER_DOCTYPE, new_name)
		self.assertEqual(doc.sales_invoice, a.name)
		self.assertEqual(doc.record_type, "RegistroAlta")
		self.assertEqual(doc.status, "PendienteEnvio")
		# indicadores del registro de subsanación (spec 04 §2.2/§9)
		self.assertEqual(doc.is_correction, 1)
		self.assertEqual(doc.prior_rejection, 1)  # su alta previa fue rechazada
		# no_prior_record queda en 0: campo del tipo ANULACIÓN del WSDL,
		# nunca viaja en un Alta (verificado en vivo contra el esquema AEAT)
		self.assertEqual(doc.no_prior_record, 0)
		# encadena sobre el ÚLTIMO registro del SIF (el de B), no sobre el de A
		self.assertEqual(doc.chain_index, 3)
		self.assertEqual(doc.previous_hash, rows[1].hash)
		data = json.loads(doc.record_json)
		self.assertEqual(data["NumSerieFactura"], a.name)
		self.assertEqual(data["PrimerRegistro"], "N")
		self.assertEqual(data["Huella"], doc.hash)
		# flags REALES del wire: reemisión con rechazo previo que NUNCA fue
		# aceptado (Subsanacion "S", RechazoPrevio "X").
		self.assertEqual(data["Subsanacion"], "S")
		self.assertEqual(data["RechazoPrevio"], "X")
		self.assertNotIn("SinRegistroPrevio", data)  # campo del tipo anulación

		# el registro original queda congelado y FUERA de lo subsanable
		original = frappe.get_doc(LEDGER_DOCTYPE, rows[0].name)
		self.assertEqual(original.status, "Incorrecto")
		self.assertEqual(original.curable, 0)

		# la factura vuelve a «Pendiente Envío» (su registro nuevo viaja)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", a.name, "es_verifactu_status"),
			emission.INVOICE_STATUS_PENDING_SEND,
		)

		# re-subsanar ya no aplica: el último registro ya no es el subsanable
		with self.assertRaises(frappe.ValidationError):
			rectification.rectify(a.name)

		# la cadena CONTINÚA sobre el registro de subsanación
		c = self._draft()
		c.submit()
		records = self._register_in_chain()
		self.assertEqual([r.chain_index for r in records], [1, 2, 3, 4])
		self.assertEqual(records[3].previous_hash, doc.hash)


class TestInOrderRectification(BaseRectification):
	"""Subsanación EN ORDEN (spec 04 §9): con mandatory_in_order_cure solo
	se subsana la factura cuyo registro erróneo sea el más antiguo
	pendiente/erróneo del SIF."""

	def _two_erroneous(self):
		self._activate()
		a, b = self._draft(), self._draft()
		a.submit()
		b.submit()
		rows = self._register_in_chain()
		self._drain_with_mock(
			self._adapted_seed(
				[
					(rows[0].name, a.name, "Incorrecto", 3000, DESC_DUPLICADO),
					(rows[1].name, b.name, "Incorrecto", 3000, DESC_DUPLICADO),
				]
			)
		)
		return a, b, rows

	def test_mandatory_order_blocks_the_newest(self):
		a, b, rows = self._two_erroneous()
		frappe.db.set_value("Company", self.company, "es_verifactu_mandatory_in_order_cure", 1)

		# la MÁS NUEVA no puede subsanarse: su registro no es el más antiguo
		with self.assertRaises(frappe.ValidationError) as ctx:
			rectification.rectify(b.name)
		# el remedio nombra al registro bloqueante (el más antiguo)
		self.assertIn(rows[0].name, str(ctx.exception))

		# la más antigua sí
		self.assertTrue(frappe.db.get_value(LEDGER_DOCTYPE, rectification.rectify(a.name), "is_correction"))

		# subsanada la más antigua, la siguiente queda liberada
		self.assertTrue(rectification.rectify(b.name))

	def test_without_order_both_ok(self):
		a, b, _rows = self._two_erroneous()  # regla OFF (reset del setUp)

		for si in (a, b):
			self.assertTrue(rectification.rectify(si.name))

		# ambas subsanadas: no queda nada subsanable en el SIF
		self.assertFalse(frappe.db.exists(LEDGER_DOCTYPE, {"company": self.company, "curable": 1}))


class TestRectificationPermissions(BaseRectification):
	"""Permiso explícito por empresa+propósito en rectify (doc 12 §18)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", UNAUTHORIZED_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": UNAUTHORIZED_USER,
					"first_name": "ES",
					"last_name": "Sin Permiso Subsanacion",
					"enabled": 1,
				}
			).insert(ignore_permissions=True)
		# usuario distinto por test: la clase comparte transacción y el rol
		# añadido por un test NO puede regalar el permiso al otro (los tests
		# deben ser independientes del orden de ejecución).
		if not frappe.db.exists("User", AUTHORIZED_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": AUTHORIZED_USER,
					"first_name": "ES",
					"last_name": "Con Permiso Subsanacion",
					"roles": [{"role": "Accounts Manager"}],
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

	def _erroneous(self):
		self._activate()
		a = self._draft()
		a.submit()
		rows = self._register_in_chain()
		self._drain_with_mock(
			self._adapted_seed([(rows[0].name, a.name, "Incorrecto", 3000, DESC_DUPLICADO)])
		)
		return a

	def test_user_without_permission_error(self):
		a = self._erroneous()
		frappe.set_user(UNAUTHORIZED_USER)
		self.addCleanup(frappe.set_user, "Administrator")

		with self.assertRaises(frappe.PermissionError):
			rectification.rectify(a.name)

	def test_user_with_authorized_role_ok(self):
		"""Con Accounts Manager (rol con permiso AEAT por defecto) +
		credencial habilitada → subsana normal."""
		a = self._erroneous()

		frappe.set_user(AUTHORIZED_USER)
		self.addCleanup(frappe.set_user, "Administrator")

		new_name = rectification.rectify(a.name)
		self.assertTrue(frappe.db.get_value(LEDGER_DOCTYPE, new_name, "is_correction"))


class TestRectifiableInvoicesReport(BaseRectification):
	"""Report «Rectifiable Invoices» (spec 04 §9): columnas en español y
	filas ordenadas por cadena del SIF (la más antigua primero)."""

	def test_rows_and_chain_order(self):
		self._activate()
		a, b = self._draft(), self._draft()
		a.submit()
		b.submit()
		rows = self._register_in_chain()
		self._drain_with_mock(
			self._adapted_seed(
				[
					(rows[0].name, a.name, "Incorrecto", 3000, DESC_DUPLICADO),
					(rows[1].name, b.name, "Incorrecto", 3000, DESC_DUPLICADO),
				]
			)
		)

		# Aislamiento: se filtra por la compañía de PRUEBAS — el site tiene
		# registros VIVOS de la empresa real y el informe global los lista.
		columns, data = report.execute({"company": self.company})
		self.assertEqual(
			[c["label"] for c in columns],
			[
				"Factura",
				"Compañía",
				"Fecha",
				"Tipo",
				"Código de error AEAT",
				"Descripción del error AEAT",
				"Pendiente desde",
			],
		)
		self.assertEqual([row["invoice"] for row in data], [a.name, b.name])
		self.assertEqual([row["company"] for row in data], [self.company, self.company])
		self.assertEqual([row["type"] for row in data], ["F1", "F1"])
		self.assertEqual([row["error_code"] for row in data], ["3000", "3000"])
		self.assertEqual([row["error_description"] for row in data], [DESC_DUPLICADO, DESC_DUPLICADO])
		self.assertTrue(all(row["date"] for row in data))
		self.assertTrue(all(row["pending_since"] for row in data))

		# subsanada la más antigua, el informe solo muestra la pendiente
		rectification.rectify(a.name)
		_, data = report.execute({"company": self.company})
		self.assertEqual([row["invoice"] for row in data], [b.name])

		# filtro por compañía
		_, data = report.execute({"company": self.company})
		self.assertEqual([row["invoice"] for row in data], [b.name])


class TestStaleOutbox(BaseRectification):
	"""Alerta diaria de outbox estancado (spec 04 §8): registros
	PendienteEnvio parados > 24 h → incidencia por los DOS canales."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_notified_user()

	def test_stale_notifies_both_channels(self):
		self._activate(notify=True)
		frappe.db.set_value("Company", self.company, "es_incidents_email", "asesor@test.example.com")
		self.addCleanup(frappe.db.set_value, "Company", self.company, "es_incidents_email", None)

		a, b = self._draft(), self._draft()
		a.submit()
		b.submit()
		rows = self._register_in_chain()

		# el registro de A lleva 30 h parado; el de B acaba de nacer
		stale_since = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-30)
		frappe.db.set_value(LEDGER_DOCTYPE, rows[0].name, {"modified": stale_since}, update_modified=False)

		with unittest.mock.patch("frappe.sendmail") as sendmail:
			alerted = tasks.alert_stale_outbox()

		# solo el VIEJO dispara el aviso (idempotencia diaria: el recordatorio
		# es intencionado, pero el fresco no es estancado)
		self.assertEqual(alerted, [{"company": self.company, "records": [rows[0].name]}])

		# canal email externo (es_incidents_email)
		sendmail.assert_called_once()
		self.assertEqual(sendmail.call_args.kwargs["recipients"], ["asesor@test.example.com"])
		self.assertIn("estancado", sendmail.call_args.kwargs["subject"])

		# canal in-app (Notification Log para el rol de la compañía)
		alerts = self._in_app_alerts()
		self.assertTrue(any("estancado" in subject for subject in alerts), alerts)

	def test_hooks_scheduler_daily(self):
		"""La entrada daily del planificador (mismo estilo del cron del 5a)
		existe y la tarea es resoluble por su vía real."""
		hooks = frappe.get_hooks("scheduler_events", app_name="erpnext_spain")
		self.assertIn("erpnext_spain.es_verifactu.tasks.daily", hooks.get("daily") or [])
		self.assertTrue(callable(frappe.get_attr("erpnext_spain.es_verifactu.tasks.alert_stale_outbox")))
		self.assertEqual(tasks.STALE_OUTBOX_HOURS_DEFAULT, 24)


class TestResponseIdempotency(BaseRectification):
	"""Idempotencia por respuesta (spec 04 §9): reprocesar la MISMA
	respuesta no duplica registros de reintento."""

	def test_reprocessed_response_no_duplicate_retries(self):
		self._activate()
		a = self._draft()
		a.submit()
		original = self._register_in_chain()[0]
		response = self._adapted_seed(
			[(original.name, a.name, "Incorrecto", 4108, "Error transitorio de la AEAT.")]
		)
		self._drain_with_mock(response)

		# reproceso de la MISMA respuesta (mismo documento persistido)
		response_doc = frappe.get_doc(
			RESPONSE_DOCTYPE, frappe.db.get_value(LEDGER_DOCTYPE, original.name, "response")
		)
		VerifactuDriver().process_response(response, response_doc)
		VerifactuDriver().process_response(response, response_doc)

		records = self._register_in_chain()
		self.assertEqual(len(records), 2)  # original + UN reintento
		self.assertEqual([r.status for r in records], ["Incorrecto", "PendienteEnvio"])
		self.assertEqual([r.prior_rejection for r in records], [0, 1])
