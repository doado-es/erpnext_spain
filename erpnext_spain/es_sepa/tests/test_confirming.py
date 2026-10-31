# Confirming en formato AEF (spec 12, criterios 1-6).

import frappe
from frappe.utils import add_days, flt, nowdate

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.closing import leaf
from erpnext_spain.es_sepa import confirming
from erpnext_spain.es_sepa.tests.test_sepa import SepaTestCase, make_iban


class TestConfirming(SepaTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Una cuenta por opción contable: cada cuenta tiene su norma «Confirming».
		cls.accounts = {confirming.OPTION_A: cls.company_account}
		ledger = cls.bank_ledger("5722", "Banco confirming")
		cls.accounts[confirming.OPTION_B] = cls.bank_account(
			"Cuenta confirming B", make_iban("21000418450200051998"), company_account=ledger
		)
		cls.ensure_norms(
			cls.accounts[confirming.OPTION_A],
			{"Confirming": "000"},
			contract_number="CONF-A",
			accounting_option=confirming.OPTION_A,
		)
		cls.ensure_norms(
			cls.accounts[confirming.OPTION_B],
			{"Confirming": "000"},
			contract_number="CONF-B",
			accounting_option=confirming.OPTION_B,
			debt_account=leaf(cls.company, "520"),
		)

	def supplier(self, name: str, account_number: str, email: bool = True, address: bool = True) -> str:
		supplier, _account = self.party("Supplier", name, account_number, address=address)
		frappe.db.set_value(
			"Supplier",
			supplier,
			{
				"tax_id": "B12345674",
				"email_id": f"{supplier[-6:]}@example.com".replace(" ", "") if email else None,
			},
		)
		frappe.clear_document_cache("Supplier", supplier)
		return supplier

	def invoice(self, supplier: str, rate: float, due_days: int = 30):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": supplier,
				"bill_no": frappe.generate_hash(length=6).upper(),
				"bill_date": nowdate(),
				"due_date": add_days(nowdate(), due_days),
				"credit_to": pgc.account_by_number(self.company, "4000"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"rate": rate,
						"expense_account": pgc.account_by_number(self.company, "6000"),
						"cost_center": self.cost_center,
					}
				],
			}
		).insert()
		pi.submit()
		frappe.db.set_value(
			"Payment Schedule", {"parent": pi.name}, "mode_of_payment", confirming.CONFIRMING_MODE
		)
		return pi

	def debit_note(self, pi, amount: float):
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

		note = make_debit_note(pi.name)
		note.items[0].rate = amount
		note.bill_no = frappe.generate_hash(length=6).upper()
		note.insert()
		note.submit()
		return note

	def batch(self, option: str, rows=None):
		doc = frappe.get_doc(
			{
				"doctype": "ES Confirming Batch",
				"company": self.company,
				"bank_account": self.accounts[option],
				"remittance_date": nowdate(),
				"lines": rows or confirming.get_invoices(self.company),
			}
		)
		return doc

	def test_file_with_credit_note(self):
		"""Criterio 1: facturas y un abono de dos proveedores; fichero AEF de 250 posiciones."""
		first = self.supplier("_Test ES Proveedor Confirming 1", "21000418450200051432")
		second = self.supplier("_Test ES Proveedor Confirming 2", "21000418450200051441")
		invoice = self.invoice(first, 1000)
		self.invoice(second, 500)
		self.debit_note(invoice, 100)
		rows = [r for r in confirming.get_invoices(self.company) if r["supplier"] in (first, second)]
		self.assertEqual(sorted(flt(r["amount"]) for r in rows), [-100, 500, 1000])
		batch = self.batch(confirming.OPTION_A, rows).insert()
		batch.submit()
		batch.reload()
		content = frappe.get_doc("File", {"file_url": batch.confirming_file}).get_content()
		lines = (content if isinstance(content, str) else content.decode("ascii")).splitlines()
		self.assertTrue(all(len(line) == 250 for line in lines))
		self.assertEqual(
			[line[0] for line in lines], ["1", "2", "3", "4", "5", "6", "6", "3", "4", "5", "6", "7"]
		)
		self.assertEqual(lines[0][170:172], "FU")
		credit = next(line for line in lines if line[0] == "6" and line[21] == "-")
		self.assertEqual(int(credit[22:37]), 10000)
		self.assertEqual(int(lines[-1][1:13]), 2)  # proveedores (registros 3)
		self.assertEqual(int(lines[-1][13:28]), 140000)  # 1.000 + 500 - 100

	def test_missing_supplier_data_blocks(self):
		"""Criterio 2."""
		supplier = self.supplier(
			"_Test ES Proveedor Confirming sin CP", "21000418450200051450", address=False
		)
		pi = self.invoice(supplier, 50)
		rows = [r for r in confirming.get_invoices(self.company) if r["purchase_invoice"] == pi.name]
		batch = self.batch(confirming.OPTION_A, rows).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "_Test ES Proveedor Confirming sin CP"):
			batch.submit()

	def test_overdue_invoice_rejected(self):
		"""Criterio 3."""
		supplier = self.supplier("_Test ES Proveedor Confirming vencido", "21000418450200051469")
		pi = self.invoice(supplier, 50, due_days=0)
		frappe.db.set_value("Purchase Invoice", pi.name, "due_date", add_days(nowdate(), -5))
		rows = [{"purchase_invoice": pi.name, "amount": 50}]
		with self.assertRaisesRegex(frappe.ValidationError, "antes de la fecha de la remesa"):
			self.batch(confirming.OPTION_A, rows).insert()

	def test_option_a_matched_with_statement(self):
		"""Criterio 4: el cargo del extracto se casa con los pagos y las facturas quedan pagadas."""
		from erpnext_spain.es_bancos import importer
		from erpnext_spain.es_bancos.tests.test_banking import norma43_file

		supplier = self.supplier("_Test ES Proveedor Confirming A", "21000418450200051478")
		pi = self.invoice(supplier, 300)
		rows = [r for r in confirming.get_invoices(self.company) if r["purchase_invoice"] == pi.name]
		batch = self.batch(confirming.OPTION_A, rows).insert()
		batch.submit()
		payments = confirming.register_maturity(batch.name, nowdate())
		self.assertAlmostEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 0)
		iban = frappe.db.get_value("Bank Account", self.accounts[confirming.OPTION_A], "iban")
		importer.import_norma43(
			self.company,
			norma43_file(
				[{"ccc": iban[4:24], "opening": 1000, "movements": [(nowdate(), -300, "99", batch.name)]}]
			),
		)
		transaction = frappe.get_doc("Bank Transaction", {"description": ["like", f"%{batch.name}%"]})
		self.assertEqual([row.payment_entry for row in transaction.payment_entries], payments)
		self.assertEqual(transaction.status, "Reconciled")

	def test_option_b_entries_balance(self):
		"""Criterio 5: con reclasificación, los asientos cuadran y llevan centro de coste."""
		supplier = self.supplier("_Test ES Proveedor Confirming B", "21000418450200051487")
		pi = self.invoice(supplier, 400)
		rows = [r for r in confirming.get_invoices(self.company) if r["purchase_invoice"] == pi.name]
		batch = self.batch(confirming.OPTION_B, rows).insert()
		batch.submit()
		batch.reload()
		remittance = frappe.get_doc("Journal Entry", batch.remittance_entry)
		self.assertAlmostEqual(remittance.total_debit, remittance.total_credit)
		self.assertTrue(all(row.cost_center for row in remittance.accounts))
		self.assertAlmostEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 0)
		maturity = frappe.get_doc("Journal Entry", confirming.register_maturity(batch.name, nowdate())[0])
		self.assertAlmostEqual(maturity.total_debit, 400)
		self.assertTrue(all(row.cost_center for row in maturity.accounts))

	def test_requires_role(self):
		"""Criterio 6."""
		user = "es-sepa-test@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "SEPA"}).insert()
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				confirming.register_maturity("CONF-X")
		finally:
			frappe.set_user("Administrator")
