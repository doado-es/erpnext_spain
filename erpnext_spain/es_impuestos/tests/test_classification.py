# Clasificación fiscal de las filas de impuestos al validar (spec 03 §5, criterios 4 y 6).

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_impuestos import initial_data, invoice
from erpnext_spain.es_impuestos.tests.test_initial_data import (
	apply_template,
	ensure_item,
	ensure_party,
	make_company,
)

CLASSIFICATION = ("es_tax_type", "es_vat_classification", "es_operation_type", "es_regime_key")


class TestClassificationOnValidate(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Clasificación", "_TECL")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.item = ensure_item("_Test ES Servicio Clasificación")
		cls.customer = ensure_party("Customer", "_Test ES Cliente Clasificación")

	def setUp(self):
		frappe.db.set_value("Company", self.company, "es_require_tax_classification", 0)

	def invoice(self, with_template: bool = True):
		template = initial_data.template_name(self.company, "Sales Taxes and Charges Template", "IVA 21 %")
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"debit_to": pgc.account_by_number(self.company, "4300"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"rate": 100,
						"income_account": pgc.account_by_number(self.company, "7050"),
						"cost_center": self.cost_center,
					}
				],
				"taxes_and_charges": template,
			}
		)
		apply_template(si)
		if not with_template:
			si.taxes_and_charges = None
		for row in si.taxes:
			for field in CLASSIFICATION:
				row.set(field, None)
		return si

	def test_empty_rows_copied_from_template(self):
		si = self.invoice().insert()
		row = si.taxes[0]
		self.assertEqual(row.es_tax_type, "IVA")
		self.assertEqual(row.es_vat_classification, "S1")
		self.assertTrue(row.es_operation_type)

	def test_informed_values_not_overwritten(self):
		si = self.invoice()
		si.taxes[0].es_vat_classification = "S2"
		si.insert()
		self.assertEqual(si.taxes[0].es_vat_classification, "S2")

	def test_required_blocks_submit_but_not_draft(self):
		frappe.db.set_value("Company", self.company, "es_require_tax_classification", 1)
		si = self.invoice(with_template=False)
		si.taxes[0].es_tax_type = "IVA"
		si.insert()  # el borrador se guarda
		with self.assertRaisesRegex(frappe.ValidationError, "calificación o exención"):
			si.submit()

		si.reload()
		si.taxes[0].es_vat_classification = "S1"
		si.taxes[0].es_operation_type = "Interior"
		si.submit()
		self.assertEqual(si.docstatus, 1)

	def test_untyped_tax_account_row_required(self):
		frappe.db.set_value("Company", self.company, "es_require_tax_classification", 1)
		si = self.invoice(with_template=False).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "tipo de impuesto"):
			si.submit()

	def test_non_pgc_company_requires_nothing(self):
		other = make_company("_Test ES Clasificación sin PGC", "_TECS")
		frappe.db.set_value("Company", other, "es_require_tax_classification", 1)
		doc = frappe.get_doc(
			{"doctype": "Sales Invoice", "company": other, "docstatus": 1, "taxes": [{"account_head": "x"}]}
		)
		invoice.validate_regional(doc)  # no lanza
