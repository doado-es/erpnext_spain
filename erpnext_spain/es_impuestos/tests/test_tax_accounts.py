# Mapa de cuentas de impuestos (informe ES Tax Accounts).

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_impuestos.report.es_tax_accounts import es_tax_accounts as report
from erpnext_spain.es_impuestos.tests.test_initial_data import make_company

BAD = "_Test ES Mapa mal clasificada"


class TestTaxAccounts(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Mapa Impuestos", "_TEMI")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)

	def rows(self):
		return report.execute({"company": self.company})[1]

	def test_initial_templates_map_to_official_names(self):
		by_name = {}
		for row in self.rows():
			by_name.setdefault(row["official_name"], []).append(row)
		for name, prefix in (
			("IVA repercutido", "477"),
			("IVA soportado deducible en operaciones interiores corrientes", "472"),
		):
			with self.subTest(name=name):
				self.assertIn(name, by_name)
				accounts = {r["account"] for r in by_name[name]}
				numbers = {frappe.db.get_value("Account", a, "account_number") for a in accounts}
				self.assertTrue(all(str(n).startswith(prefix) for n in numbers))
		self.assertIn("Retenciones IRPF practicadas", by_name)
		self.assertTrue(any("21 %" in r["rates"] for r in by_name["IVA repercutido"]))
		# Las plantillas iniciales están bien clasificadas: nada que revisar.
		self.assertEqual(
			[(r["official_name"], r["issue"], r["templates"]) for r in self.rows() if r["issue"]], []
		)

	def test_flags_unclassified_rows_and_wrong_accounts(self):
		template = frappe.get_doc(
			{
				"doctype": "Sales Taxes and Charges Template",
				"title": BAD,
				"company": self.company,
				"taxes": [
					{
						"charge_type": "On Net Total",
						"account_head": pgc.account_by_number(self.company, "4720"),
						"description": "IVA mal",
						"rate": 21,
						"es_tax_type": "IVA",
						"es_vat_classification": "S1",
						"es_operation_type": "Interior",
					},
					{
						"charge_type": "On Net Total",
						"account_head": pgc.account_by_number(self.company, "4770"),
						"description": "Sin clasificar",
						"rate": 5,
					},
				],
			}
		).insert()
		self.addCleanup(frappe.delete_doc, "Sales Taxes and Charges Template", template.name)
		rows = [r for r in self.rows() if template.name in r["templates"]]
		issues = {r["official_name"]: r["issue"] for r in rows}
		self.assertIn("477", issues["IVA repercutido"])
		self.assertIn("sin tipo de impuesto", issues[""])

	def test_requires_company(self):
		self.assertRaises(frappe.ValidationError, report.execute, {})

	def test_official_name_rules(self):
		row = frappe._dict
		self.assertEqual(
			report.official_name(
				row(
					es_tax_type="IVA",
					es_self_assessed=1,
					es_operation_type="Adquisición intracomunitaria de bienes",
				),
				"purchase",
			),
			"IVA devengado en adquisiciones intracomunitarias",
		)
		self.assertEqual(
			report.official_name(row(es_tax_type="IVA", es_deductibility="No deducible"), "purchase"),
			"IVA soportado no deducible",
		)
		self.assertEqual(
			report.official_name(row(es_tax_type="Retención IRPF"), "sale"),
			"Retenciones e ingresos a cuenta soportados",
		)
		self.assertIsNone(report.official_name(row(), "sale"))
