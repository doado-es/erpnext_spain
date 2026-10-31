# Site tests de los doc_events de Customer/Supplier/Company (spec 14 §2, §5).
#
# La integración corre en una transacción que se revierte al terminar la
# clase, pero entre tests de la MISMA clase los cambios se ven: cada test
# fija explícitamente el modo de validación que necesita.

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.tests.fixtures import ensure_test_company

INVALID_CONTROL_DIGIT_NIF = "12345678A"  # la letra correcta es Z


class TestPartyValidation(IntegrationTestCase):
	def setUp(self):
		frappe.clear_messages()

	def _set_mode(self, mode: str):
		settings = frappe.get_doc("ES Settings")
		settings.modo_validacion_nif = mode
		settings.save(ignore_permissions=True)

	def _new_customer(self, tax_id: str | None) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "ES NIF Test " + frappe.generate_hash(length=6),
				"tax_id": tax_id,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def test_invalid_customer_nif_blocks_and_suggests(self):
		self._set_mode("Bloquear")
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._new_customer(INVALID_CONTROL_DIGIT_NIF)
		self.assertIn("¿quisiste decir `Z`?", str(ctx.exception))

	def test_invalid_customer_nif_warn_only(self):
		self._set_mode("Solo avisar")
		name = self._new_customer(INVALID_CONTROL_DIGIT_NIF)
		self.assertTrue(frappe.db.exists("Customer", name))
		alerts = [str(m) for m in frappe.get_message_log()]
		self.assertTrue(any("`Z`" in alert for alert in alerts), alerts)

	def test_customer_without_nif_saves(self):
		self._set_mode("Bloquear")
		name = self._new_customer(None)
		self.assertTrue(frappe.db.exists("Customer", name))

	def test_valid_customer_nif_saves(self):
		self._set_mode("Bloquear")
		name = self._new_customer("12345678Z")
		self.assertTrue(frappe.db.exists("Customer", name))

	def test_foreign_customer_without_pattern_saves(self):
		self._set_mode("Bloquear")
		name = self._new_customer("FR12345678")
		self.assertTrue(frappe.db.exists("Customer", name))

	def test_foreign_supplier_saves(self):
		self._set_mode("Bloquear")
		doc = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "ES NIF Test Supplier " + frappe.generate_hash(length=6),
				"country": "United Kingdom",
				"tax_id": "FR12345678",
			}
		)
		doc.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Supplier", doc.name))

	def test_spain_supplier_invalid_nif_blocks(self):
		self._set_mode("Bloquear")
		doc = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "ES NIF Test Supplier " + frappe.generate_hash(length=6),
				"country": "Spain",
				"tax_id": INVALID_CONTROL_DIGIT_NIF,
			}
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.insert(ignore_permissions=True)
		self.assertIn("¿quisiste decir `Z`?", str(ctx.exception))

	def test_spain_customer_by_address_and_garbage_nif_blocks(self):
		self._set_mode("Bloquear")
		name = self._new_customer(None)

		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "ES NIF Test Address " + frappe.generate_hash(length=6),
				"address_type": "Billing",
				"address_line1": "Calle Test 1",
				"city": "A Coruña",
				"country": "Spain",
				"is_primary_address": 1,
				"links": [{"link_doctype": "Customer", "link_name": name}],
			}
		).insert(ignore_permissions=True)

		customer = frappe.get_doc("Customer", name)
		customer.tax_id = "85810678"  # ni patrón español ni válido
		with self.assertRaises(frappe.ValidationError) as ctx:
			customer.save(ignore_permissions=True)
		self.assertIn("no tiene formato de NIF español", str(ctx.exception))

	def test_spain_company_invalid_nif_always_blocks(self):
		self._set_mode("Solo avisar")
		doc = frappe.get_doc("Company", ensure_test_company())
		doc.country = "Spain"
		doc.tax_id = INVALID_CONTROL_DIGIT_NIF
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("¿quisiste decir `Z`?", str(ctx.exception))


class TestNifCustomFields(IntegrationTestCase):
	def test_trade_name_on_customer_and_supplier(self):
		for doctype in ("Customer", "Supplier"):
			meta = frappe.get_meta(doctype)
			field = meta.get_field("es_trade_name")
			self.assertIsNotNone(field, doctype)
			self.assertEqual(field.label, "Nombre comercial")

	def test_trade_name_not_on_company(self):
		self.assertIsNone(frappe.get_meta("Company").get_field("es_trade_name"))


class TestReportCheckup(IntegrationTestCase):
	def test_report_detects_invalid_and_missing(self):
		from erpnext_spain.nif.report.es_nif_checkup.es_nif_checkup import execute

		columns, data = execute()
		self.assertEqual(len(columns), 6)

		settings = frappe.get_doc("ES Settings")
		settings.modo_validacion_nif = "Solo avisar"
		settings.save(ignore_permissions=True)

		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "ES NIF Checkup Test",
				"tax_id": INVALID_CONTROL_DIGIT_NIF,
			}
		).insert(ignore_permissions=True)
		customer_without_nif = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "ES NIF Checkup Test Sin NIF",
				"tax_id": "",
			}
		).insert(ignore_permissions=True)

		_, data = execute()
		by_id = {row["identifier"]: row for row in data}
		invalid_row = by_id.get(customer.name)
		self.assertIsNotNone(invalid_row)
		self.assertEqual(invalid_row["defect"], "letra de control")
		self.assertIn("`Z`", invalid_row["suggestion"])

		missing_row = by_id.get(customer_without_nif.name)
		self.assertIsNotNone(missing_row)
		self.assertEqual(missing_row["defect"], "ausente")
