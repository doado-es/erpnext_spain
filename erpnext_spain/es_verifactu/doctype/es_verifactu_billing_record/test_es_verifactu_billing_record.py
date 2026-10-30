# Site tests del libro «ES Verifactu Billing Record» (spec 04 §2.2/§3):
# nacimiento en PendienteEnvio, inmutabilidad de terminales (solo el
# procesador de respuestas, vía flag, transiciona) y subsanación como registro
# NUEVO (nunca edición).
#
# La caminata de dependencias del IntegrationTestCase (make_test_records)
# importaría la maquinaria de tests de erpnext para Company y Sales Invoice,
# cuyo bootstrap asume fixtures en inglés que no existen en un site localizado
# («Could not find Parent Department»): se ignoran y se usa la primera
# compañía REAL del site. Los registros no referencian facturas.

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.aeat.tests.helpers import test_company
from erpnext_spain.es_verifactu.doctype.es_verifactu_billing_record.es_verifactu_billing_record import (
	PENDING_SEND_STATE,
	RESPONSE_PROCESSOR_FLAG,
)

DOCTYPE = "ES Verifactu Billing Record"

# La caminata de dependencias del IntegrationTestCase (make_test_records)
# importaría la maquinaria de tests de erpnext para Company y Sales Invoice,
# cuyo bootstrap asume fixtures en inglés que no existen en un site localizado
# («Could not find Parent Department»): se ignoran y se usa la primera
# compañía REAL del site. Los registros no referencian facturas.
# «ES AEAT Response» también se ignora: el ignore de este módulo NO es
# transitivo — sin él la caminata entraría por el link «response» hasta
# Company y rebotaría igual (mismo patrón que test_es_aeat_credential).
IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "Sales Invoice", "ES AEAT Response"]


class TestESVerifactuBillingRecord(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()

	def setUp(self):
		frappe.set_user("Administrator")
		# La clase comparte transacción: cada test arranca sin registros.
		for nombre in frappe.get_all(DOCTYPE, filters={"company": self.company}, pluck="name"):
			frappe.delete_doc(DOCTYPE, nombre, ignore_permissions=True)

	def _new(self, **overrides) -> object:
		doc = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"company": self.company,
				"record_type": "RegistroAlta",
				"invoice_type": "F1",
				"chain_index": 1,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_born_pending_send(self):
		doc = self._new()
		self.assertEqual(doc.status, PENDING_SEND_STATE)

	def test_born_in_terminal_state_blocks(self):
		"""La máquina de estados (spec 04 §3): creación → PendienteEnvio; los
		terminales solo llegan con la respuesta de la AEAT."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._new(status="Correcto")
		self.assertIn(PENDING_SEND_STATE, str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_processor_transitions_to_terminal(self):
		doc = self._new()
		doc.flags[RESPONSE_PROCESSOR_FLAG] = True
		doc.status = "AceptadoConErrores"
		doc.response_error_code = "4107"
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "status"), "AceptadoConErrores")

	def test_direct_edit_of_terminal_blocked(self):
		doc = self._new()
		doc.flags[RESPONSE_PROCESSOR_FLAG] = True
		doc.status = "Correcto"
		doc.save(ignore_permissions=True)

		terminal = frappe.get_doc(DOCTYPE, doc.name)
		terminal.hash = "X" * 64
		with self.assertRaises(frappe.ValidationError) as ctx:
			terminal.save(ignore_permissions=True)
		self.assertIn("congelado", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))
		self.assertIn("subsanación", str(ctx.exception).lower())

	def test_regression_to_pending_without_flag_blocked(self):
		doc = self._new()
		doc.flags[RESPONSE_PROCESSOR_FLAG] = True
		doc.status = "Incorrecto"
		doc.save(ignore_permissions=True)

		terminal = frappe.get_doc(DOCTYPE, doc.name)
		terminal.status = PENDING_SEND_STATE
		with self.assertRaises(frappe.ValidationError):
			terminal.save(ignore_permissions=True)

	def test_correction_creates_new_record(self):
		"""La subsanación NUNCA edita (spec 04 §2.2): el registro previo queda
		intacto y la corrección es un registro nuevo encadenado con flag."""
		rechazado = self._new()
		rechazado.flags[RESPONSE_PROCESSOR_FLAG] = True
		rechazado.status = "Incorrecto"
		rechazado.hash = "H1"
		rechazado.save(ignore_permissions=True)

		correction = self._new(
			is_correction=1,
			prior_rejection=1,
			chain_index=2,
			previous_hash="H1",
		)
		self.assertEqual(correction.is_correction, 1)
		self.assertEqual(correction.status, PENDING_SEND_STATE)

		# el original NO se tocó
		original = frappe.db.get_value(
			DOCTYPE, rechazado.name, ["status", "hash", "is_correction"], as_dict=True
		)
		self.assertEqual(original.status, "Incorrecto")
		self.assertEqual(original.hash, "H1")
		self.assertEqual(original.is_correction, 0)

	def test_has_records_and_pending_count(self):
		from erpnext_spain.es_verifactu.doctype.es_verifactu_billing_record.es_verifactu_billing_record import (
			has_records,
			pending_send_count,
		)

		self.assertFalse(has_records(self.company))
		doc = self._new()
		self.assertTrue(has_records(self.company))
		self.assertEqual(pending_send_count(self.company), 1)

		doc.flags[RESPONSE_PROCESSOR_FLAG] = True
		doc.status = "Correcto"
		doc.save(ignore_permissions=True)
		self.assertEqual(pending_send_count(self.company), 0)
		self.assertTrue(has_records(self.company))
