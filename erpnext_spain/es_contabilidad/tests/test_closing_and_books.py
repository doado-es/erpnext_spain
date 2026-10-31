# Sumas y saldos, libro diario y asientos de cierre PGC (spec 04 §4-§7, criterios 7 y 9).

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, getdate, nowdate

from erpnext_spain.es_contabilidad import closing, pgc
from erpnext_spain.es_contabilidad.report.es_journal_book import es_journal_book
from erpnext_spain.es_contabilidad.report.es_trial_balance_by_level import es_trial_balance_by_level
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company


class TestClosingAndBooks(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Cierre", "_TECI")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "Normal", dry_run=False)
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.year = frappe.db.get_value(
			"Fiscal Year", {"year_start_date": ["<=", nowdate()], "year_end_date": [">=", nowdate()]}
		)
		cls.start, cls.end = frappe.db.get_value(
			"Fiscal Year", cls.year, ["year_start_date", "year_end_date"]
		)
		cls.journal([("1000", 0, 10000), ("5720", 10000, 0)], is_opening="Yes", posting_date=cls.start)
		cls.journal([("3000", 1000, 0), ("5720", 0, 1000)])  # existencia inicial de mercaderías
		cls.journal([("6000", 400, 0), ("5720", 0, 400)])
		cls.journal([("5720", 1000, 0), ("9400", 0, 1000)])  # subvención imputada al patrimonio

	@classmethod
	def journal(cls, lines, **extra):
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": cls.company,
				"posting_date": extra.pop("posting_date", nowdate()),
				**extra,
				"accounts": [
					{
						"account": pgc.account_by_number(cls.company, number),
						"debit_in_account_currency": debit,
						"credit_in_account_currency": credit,
						"cost_center": cls.cost_center,
					}
					for number, debit, credit in lines
				],
			}
		)
		je.insert()
		je.submit()
		return je

	def balance(self, number: str) -> float:
		rows = frappe.get_all(
			"GL Entry",
			filters={"account": pgc.account_by_number(self.company, number), "is_cancelled": 0},
			fields=["debit", "credit"],
		)
		return flt(sum(r.debit - r.credit for r in rows), 2)

	def test_trial_balance_levels(self):
		"""Criterio 7: debe = haber en todos los niveles y el nivel 3 suma el 1."""
		base = {"company": self.company, "from_date": self.start, "to_date": self.end}
		by_level = {}
		for level in ("1", "2", "3", "4", "Cuenta"):
			_columns, rows = es_trial_balance_by_level.execute({**base, "level": level})
			total = rows[-1]
			with self.subTest(level=level):
				self.assertAlmostEqual(total["debit"], total["credit"])
				self.assertAlmostEqual(total["closing"], 0)
			by_level[level] = rows[:-1]
		for group in "1235679":
			level_1 = sum(r["closing"] for r in by_level["1"] if r["account_number"] == group)
			level_3 = sum(r["closing"] for r in by_level["3"] if r["account_number"].startswith(group))
			self.assertAlmostEqual(level_1, level_3, msg=group)
		names = {r["account_number"]: r["account_name"] for r in by_level["1"]}
		self.assertEqual(names["5"], "Cuentas financieras")

	def test_journal_book_numbering(self):
		_columns, rows = es_journal_book.execute({"company": self.company, "fiscal_year": self.year})
		numbers = [r["entry_no"] for r in rows if r.get("entry_no")]
		self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
		self.assertEqual(rows[0]["entry_class"], "Apertura")
		self.assertAlmostEqual(rows[-1]["debit"], rows[-1]["credit"])
		# Estable entre ejecuciones.
		_columns, again = es_journal_book.execute({"company": self.company, "fiscal_year": self.year})
		self.assertEqual(
			[(r.get("entry_no"), r.get("voucher_no")) for r in rows],
			[(r.get("entry_no"), r.get("voucher_no")) for r in again],
		)

	def test_inventory_regularisation(self):
		"""Criterio 9: inicial 1.000 en 300, final 1.500 → 300 a 1.500 y 610 acreedora en 500."""
		item = "_Test ES Mercadería cierre"
		if not frappe.db.exists("Item", item):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": item,
					"item_group": "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 1,
				}
			).insert()
		warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": self.company,
				"items": [
					{
						"item_code": item,
						"qty": 10,
						"basic_rate": 150,
						"t_warehouse": warehouse,
						"expense_account": pgc.account_by_number(self.company, "6000"),
						"cost_center": self.cost_center,
					}
				],
			}
		)
		entry.insert()
		entry.submit()
		proposal = closing.regularise_inventory(self.company, nowdate(), dry_run=True)
		goods = next(r for r in proposal["lines"] if r["class"] == "Mercaderías")
		self.assertAlmostEqual(goods["initial"], 1000)
		self.assertAlmostEqual(goods["final"], 1500)  # valoración del Stock Ledger sin inventario permanente

		result = closing.regularise_inventory(self.company, nowdate(), dry_run=False)
		je = frappe.get_doc("Journal Entry", result["journal_entry"])
		self.assertEqual(je.docstatus, 0)  # en borrador para revisarlo
		je.submit()
		self.assertAlmostEqual(self.balance("3000"), 1500)
		self.assertAlmostEqual(self.balance("6100"), -500)
		with self.assertRaisesRegex(frappe.ValidationError, "Ya existe"):
			closing.regularise_inventory(self.company, nowdate(), dry_run=True)

	def test_corrected_final_value(self):
		result = closing.regularise_inventory(
			self.company, str(self.end), final_values={"Mercaderías": 1200}, dry_run=True
		)
		goods = next(r for r in result["lines"] if r["class"] == "Mercaderías")
		self.assertAlmostEqual(goods["final"], 1200)

	def test_transfer_groups_8_9(self):
		result = closing.transfer_groups_8_9(self.company, nowdate(), dry_run=False)
		je = frappe.get_doc("Journal Entry", result["journal_entry"])
		je.submit()
		self.assertAlmostEqual(self.balance("9400"), 0)
		self.assertAlmostEqual(self.balance("1300"), -1000)
		self.assertEqual(je.es_closing_type, closing.TRANSFER_89)
