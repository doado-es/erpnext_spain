# Activación del SII y exclusión con VeriFactu (spec 14 §1, criterio 6).

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.utils.gating import SII, VERIFACTU, active_billing_system

CIF = "B58834813"


class TestSIIActivation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = "_Test ES SII"
		if not frappe.db.exists("Company", cls.company):
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": cls.company,
					"abbr": "_TES",
					"country": "Spain",
					"default_currency": "EUR",
					"chart_of_accounts": "Standard",
					"tax_id": CIF,
				}
			).insert()

	def setUp(self):
		frappe.db.set_value("Company", self.company, {"es_sii_enabled": 0, "es_verifactu_enabled": 0})

	def test_activate_sii_in_test_mode(self):
		doc = frappe.get_doc("Company", self.company)
		doc.es_sii_enabled = 1
		doc.save()
		self.assertEqual(doc.es_sii_test_mode, "Pruebas")
		self.assertEqual(active_billing_system(self.company), SII)

	def test_sii_and_verifactu_are_exclusive(self):
		frappe.db.set_value("Company", self.company, "es_verifactu_enabled", 1)
		doc = frappe.get_doc("Company", self.company)
		doc.es_sii_enabled = 1
		with self.assertRaisesRegex(frappe.ValidationError, "SII y VeriFactu"):
			doc.save()

	def test_both_forced_means_none(self):
		"""Si una escritura sin validación deja los dos activos, ninguno genera nada."""
		frappe.db.set_value("Company", self.company, {"es_sii_enabled": 1, "es_verifactu_enabled": 1})
		self.assertIsNone(active_billing_system(self.company))
		self.assertTrue(
			frappe.db.exists("Error Log", {"method": f"SII y VeriFactu activos a la vez en {self.company}"})
		)

	def test_verifactu_only(self):
		frappe.db.set_value("Company", self.company, "es_verifactu_enabled", 1)
		self.assertEqual(active_billing_system(self.company), VERIFACTU)

	def test_sii_company_does_not_use_draft_names(self):
		"""El SII no activa la numeración de borradores de VeriFactu."""
		from erpnext_spain.es_verifactu.invoice import uses_draft_naming

		frappe.db.set_value("Company", self.company, "es_sii_enabled", 1)
		self.assertFalse(uses_draft_naming(self.company))
