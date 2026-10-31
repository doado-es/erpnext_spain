# Datos iniciales generales (spec 09 §2 y §3 g; criterios 1, 2, 4 y 7).

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.erpnext_spain import initial_data
from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company


class TestGlobalInitialData(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		initial_data.ensure_global_records()

	def test_records_exist_and_second_run_creates_nothing(self):
		for name in initial_data.EXTRA_MODES_OF_PAYMENT:
			self.assertTrue(frappe.db.exists("Mode of Payment", name))
		for name in initial_data.PAYMENT_TERMS_TEMPLATES:
			self.assertTrue(frappe.db.exists("Payment Terms Template", name))
		self.assertTrue(frappe.db.exists("Holiday List", initial_data.HOLIDAY_LIST))
		self.assertTrue(frappe.db.exists("Address Template", "Spain"))
		self.assertEqual(
			initial_data.ensure_global_records(), {k: [] for k in initial_data.ensure_global_records()}
		)

	def test_payment_terms_within_legal_maximum(self):
		"""Ley 3/2004: ningún plazo supera los 60 días."""
		for name in initial_data.PAYMENT_TERMS_TEMPLATES:
			for row in frappe.get_doc("Payment Terms Template", name).terms:
				self.assertLessEqual(row.credit_days, 60)
			self.assertAlmostEqual(
				sum(r.invoice_portion for r in frappe.get_doc("Payment Terms Template", name).terms), 100
			)

	def test_holidays(self):
		doc = frappe.get_doc("Holiday List", initial_data.HOLIDAY_LIST)
		dates = {str(row.holiday_date) for row in doc.holidays}
		self.assertIn("2026-10-12", dates)
		self.assertIn("2027-12-08", dates)

	def test_missing_year_added_without_touching_existing(self):
		doc = frappe.get_doc("Holiday List", initial_data.HOLIDAY_LIST)
		doc.append("holidays", {"holiday_date": "2026-03-19", "description": "Festivo local del usuario"})
		doc.save()
		original = dict(initial_data.NATIONAL_HOLIDAYS)
		try:
			initial_data.NATIONAL_HOLIDAYS[2028] = [("2028-01-01", "Año Nuevo")]
			self.assertEqual(initial_data.ensure_holiday_list(), [f"{initial_data.HOLIDAY_LIST} 2028"])
		finally:
			initial_data.NATIONAL_HOLIDAYS.clear()
			initial_data.NATIONAL_HOLIDAYS.update(original)
		doc.reload()
		dates = {str(row.holiday_date) for row in doc.holidays}
		self.assertIn("2026-03-19", dates)
		self.assertIn("2028-01-01", dates)
		self.assertEqual(str(doc.to_date), "2028-12-31")

	def test_address_format_and_user_changes_kept(self):
		from frappe.contacts.doctype.address.address import get_address_display

		html = get_address_display(
			{
				"address_line1": "Calle Mayor 1",
				"pincode": "15001",
				"city": "A Coruña",
				"state": "A Coruña",
				"country": "Spain",
			}
		)
		self.assertIn("15001 A Coruña", html)
		frappe.db.set_value("Address Template", "Spain", "template", "{{ city }}")
		initial_data.ensure_address_template()
		self.assertEqual(frappe.db.get_value("Address Template", "Spain", "template"), "{{ city }}")


class TestCompanyInitialData(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Datos iniciales", "_TEDI")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		cls.other = make_company("_Test ES Datos iniciales sin PGC", "_TEDS")

	def test_bank_rules_and_mode_accounts(self):
		rules = frappe.get_all(
			"Bank Transaction Rule", filters={"company": self.company}, fields=["rule_name", "account"]
		)
		self.assertEqual(len(rules), len(initial_data.BANK_RULES))
		numbers = {frappe.db.get_value("Account", r.account, "account_number") for r in rules}
		self.assertEqual(numbers, {"6260", "6623", "7690"})
		self.assertEqual(initial_data.ensure_bank_rules(self.company), [])
		account = frappe.db.get_value(
			"Mode of Payment Account", {"parent": "Bizum", "company": self.company}, "default_account"
		)
		self.assertEqual(frappe.db.get_value("Account", account, "account_number"), "5720")

	def test_rule_matches_bank_commission(self):
		rule = frappe.get_doc(
			"Bank Transaction Rule", {"company": self.company, "rule_name": ["like", "Comisiones bancarias%"]}
		)
		movement = frappe._dict(
			company=self.company, withdrawal=3.0, deposit=0.0, description="COMISIÓN MANTENIMIENTO"
		)
		self.assertTrue(rule.evaluate_rule(movement))
		movement.description = "TRANSFERENCIA RECIBIDA"
		self.assertFalse(rule.evaluate_rule(movement))

	def test_non_pgc_company_gets_nothing(self):
		self.assertFalse(frappe.get_all("Bank Transaction Rule", filters={"company": self.other}))
		self.assertFalse(
			frappe.db.exists("Mode of Payment Account", {"company": self.other, "parent": "Bizum"})
		)
