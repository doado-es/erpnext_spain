# Tests de la acción «Aplicar plan PGC» (spec 02 §2-§3, criterios 1-5).

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_impuestos.initial_data import EXTRA_ACCOUNTS
from erpnext_spain.utils.gating import is_pgc_company


def make_company(name: str, abbr: str, country: str = "Spain") -> str:
	if not frappe.db.exists("Company", name):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": name,
				"abbr": abbr,
				"country": country,
				"default_currency": "EUR",
				"chart_of_accounts": "Standard",
			}
		).insert()
	return name


def snapshot(company: str) -> dict:
	"""Estado comparable de la compañía para comprobar que dry_run no escribe."""
	doc = frappe.get_doc("Company", company)
	return {
		"accounts": sorted(frappe.get_all("Account", filters={"company": company}, pluck="name")),
		"item_tax_templates": sorted(
			frappe.get_all("Item Tax Template", filters={"company": company}, pluck="name")
		),
		"sales_templates": sorted(
			frappe.get_all("Sales Taxes and Charges Template", filters={"company": company}, pluck="name")
		),
		"company": {
			field: doc.get(field)
			for field in [*pgc.DEFAULT_ACCOUNTS, "enable_perpetual_inventory", "es_pgc_applied"]
		},
	}


class TestApplyPGCChart(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.pymes = make_company("_Test ES PGC PYMES", "_TEPP")
		cls.normal = make_company("_Test ES PGC Normal", "_TEPN")
		cls.foreign = make_company("_Test ES PGC Alemania", "_TEPA", country="Germany")

	def setUp(self):
		frappe.set_user("Administrator")

	def test_dry_run_writes_nothing(self):
		company = make_company("_Test ES PGC Simulación", "_TEPS")
		before = snapshot(company)
		summary = pgc.apply_pgc_chart(company, "PYMES", dry_run=True)
		self.assertFalse(summary["applied"])
		self.assertGreater(summary["accounts_to_create"], 1000)
		self.assertEqual(summary["accounts_to_delete"], len(before["accounts"]))
		self.assertEqual(snapshot(company), before)

	def test_apply_both_models(self):
		for company, model in ((self.pymes, "PYMES"), (self.normal, "Normal")):
			with self.subTest(model=model):
				summary = pgc.apply_pgc_chart(company, model, dry_run=False)
				self.assertTrue(summary["applied"])
				doc = frappe.get_doc("Company", company)
				self.assertEqual(doc.es_pgc_applied, 1)
				self.assertEqual(doc.es_chart_model, model)
				self.assertEqual(doc.enable_perpetual_inventory, 0)
				self.assertTrue(is_pgc_company(company))

				# Todas las cuentas son del plan PGC: ninguna hoja sin número.
				leaves_without_number = frappe.get_all(
					"Account",
					filters={"company": company, "is_group": 0, "account_number": ["in", ["", None]]},
				)
				self.assertEqual(leaves_without_number, [])
				self.assertEqual(
					frappe.db.count("Account", {"company": company}),
					summary["accounts_to_create"] + len(EXTRA_ACCOUNTS),  # 4771 de los datos de impuestos
				)
				# Lo que ERPNext crea para España con el asistente («Spain Tax») desaparece y
				# quedan las plantillas de la app (spec 09 §3).
				for doctype in ("Item Tax Template", "Sales Taxes and Charges Template"):
					self.assertFalse(frappe.db.exists(doctype, {"company": company, "title": "Spain Tax"}))
				self.assertTrue(
					frappe.db.exists(
						"Sales Taxes and Charges Template", {"company": company, "title": "IVA 21 %"}
					)
				)

				# Cuentas por defecto (spec 02 §3).
				for field, number in pgc.DEFAULT_ACCOUNTS.items():
					value = doc.get(field)
					if number is None:
						self.assertFalse(value, field)
					else:
						self.assertEqual(
							frappe.db.get_value("Account", value, "account_number"), number, field
						)
				received = frappe.db.get_value(
					"Account", doc.default_advance_received_account, ["root_type", "account_type"]
				)
				self.assertEqual(received, ("Liability", "Receivable"))
				paid = frappe.db.get_value(
					"Account", doc.default_advance_paid_account, ["root_type", "account_type"]
				)
				self.assertEqual(paid, ("Asset", "Payable"))

				# Historial de la compañía.
				self.assertTrue(
					frappe.db.exists(
						"Comment",
						{
							"reference_doctype": "Company",
							"reference_name": company,
							"content": ["like", "%PGC%"],
						},
					)
				)

				# Ya aplicado: no se puede repetir.
				with self.assertRaises(frappe.ValidationError):
					pgc.apply_pgc_chart(company, model, dry_run=True)

	def test_foreign_company_rejected(self):
		before = snapshot(self.foreign)
		with self.assertRaises(frappe.ValidationError):
			pgc.apply_pgc_chart(self.foreign, "PYMES", dry_run=False)
		self.assertEqual(snapshot(self.foreign), before)

	def test_company_with_gl_entries_rejected(self):
		company = make_company("_Test ES PGC Con Movimientos", "_TEPM")
		cash = frappe.db.get_value("Account", {"company": company, "is_group": 0, "account_type": "Cash"})
		expense = frappe.db.get_value(
			"Account", {"company": company, "is_group": 0, "root_type": "Expense", "account_type": ""}
		)
		accounts = [expense, cash]
		cost_center = frappe.db.get_value("Company", company, "cost_center")
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": company,
				"posting_date": frappe.utils.today(),
				"accounts": [
					{"account": accounts[0], "debit_in_account_currency": 10, "cost_center": cost_center},
					{"account": accounts[1], "credit_in_account_currency": 10, "cost_center": cost_center},
				],
			}
		)
		je.insert()
		je.submit()
		before = snapshot(company)
		with self.assertRaises(frappe.ValidationError):
			pgc.apply_pgc_chart(company, "PYMES", dry_run=False)
		self.assertEqual(snapshot(company), before)

	def test_unknown_model_rejected(self):
		company = make_company("_Test ES PGC Simulación", "_TEPS")
		with self.assertRaisesRegex(frappe.ValidationError, "Simplificado"):
			pgc.apply_pgc_chart(company, "Simplificado", dry_run=True)

	def test_requires_role(self):
		user = "es_pgc_sin_rol@test.example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{"doctype": "User", "email": user, "first_name": "Sin rol", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				pgc.apply_pgc_chart(self.foreign, "PYMES", dry_run=True)
		finally:
			frappe.set_user("Administrator")


class TestBalanceSheetAfterApply(IntegrationTestCase):
	"""Criterio 2: el Balance Sheet nativo (sin plantilla) funciona y cuadra con
	asientos que tocan todas las ramas, incluidas 4070, 4380, 4751 y 5720."""

	def test_native_balance_sheet_balances(self):
		from erpnext.accounts.report.balance_sheet.balance_sheet import execute

		frappe.set_user("Administrator")
		company = make_company("_Test ES PGC Balance", "_TEPB")
		pgc.apply_pgc_chart(company, "PYMES", dry_run=False)
		customer = self._party("Customer", "_Test ES PGC Cliente")
		supplier = self._party("Supplier", "_Test ES PGC Proveedor")
		cost_center = frappe.db.get_value("Company", company, "cost_center")

		def account(number: str) -> str:
			return pgc.account_by_number(company, number)

		def journal(lines: list[tuple]) -> None:
			je = frappe.get_doc(
				{
					"doctype": "Journal Entry",
					"company": company,
					"posting_date": frappe.utils.today(),
					"accounts": [
						{
							"account": account(number),
							"debit_in_account_currency": debit,
							"credit_in_account_currency": credit,
							"cost_center": cost_center,
							"party_type": party_type,
							"party": party,
						}
						for number, debit, credit, party_type, party in lines
					],
				}
			)
			je.insert()
			je.submit()

		journal([("5720", 1000, 0, None, None), ("1000", 0, 1000, None, None)])  # capital
		journal([("4070", 200, 0, "Supplier", supplier), ("5720", 0, 200, None, None)])  # anticipo pagado
		journal([("5720", 300, 0, None, None), ("4380", 0, 300, "Customer", customer)])  # anticipo cobrado
		journal([("6230", 100, 0, None, None), ("4751", 0, 100, None, None)])  # gasto con retención

		year = frappe.db.get_value(
			"Fiscal Year",
			{"year_start_date": ["<=", frappe.utils.today()], "year_end_date": [">=", frappe.utils.today()]},
		)
		_, data, *_ = execute(
			frappe._dict(
				company=company,
				filter_based_on="Fiscal Year",
				period_start_date=None,
				from_fiscal_year=year,
				to_fiscal_year=year,
				periodicity="Yearly",
				accumulated_values=1,
			)
		)
		totals = {row.get("account_name"): row.get("total") for row in data if row.get("account_name")}
		self.assertAlmostEqual(totals["Activo"], 1300)
		self.assertAlmostEqual(totals["Pasivo"], 400)
		self.assertAlmostEqual(totals["Patrimonio neto"], 1000)
		self.assertAlmostEqual(totals["Clientes (Pasivo)"], 300)  # 4380 en el pasivo
		self.assertAlmostEqual(totals["Proveedores (Activo)"], 200)  # 4070 en el activo
		# Resultado provisional: pérdida de 100; activo = pasivo + PN + resultado.
		self.assertAlmostEqual(totals["'Provisional Profit / Loss (Credit)'"], -100)
		self.assertAlmostEqual(totals["'Total (Credit)'"], totals["Activo"])

	def _party(self, doctype: str, name: str) -> str:
		if not frappe.db.exists(doctype, name):
			field = "customer_name" if doctype == "Customer" else "supplier_name"
			frappe.get_doc({"doctype": doctype, field: name}).insert()
		return name
