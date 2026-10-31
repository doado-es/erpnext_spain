# Numeración fiscal sin VeriFactu, rectificativas, amend y situación de cobro
# (spec 05, criterios 1-6 y 8).

import unittest.mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company
from erpnext_spain.es_facturacion import collection
from erpnext_spain.es_impuestos.tests.test_initial_data import ensure_item, ensure_party

SERIES_F1 = "FN-.ABBR.-.YY.-.#####"
SERIES_R1 = "RN-.ABBR.-.YY.-.#####"
DRAFT_SERIES = "BORR-.#####"


class BillingTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Facturación", "_TEFA")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		cls.abbr = frappe.get_cached_value("Company", cls.company, "abbr")
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.customer = ensure_party("Customer", "_Test ES Cliente Facturación")
		cls.item = ensure_item("_Test ES Servicio Facturación")

	def configure(self, numbering: bool = True) -> None:
		doc = frappe.get_doc("Company", self.company)
		doc.es_fiscal_numbering = 1 if numbering else 0
		doc.es_draft_series = DRAFT_SERIES if numbering else None
		doc.set("es_invoice_series", [])
		if numbering:
			doc.append("es_invoice_series", {"series": SERIES_F1, "invoice_type": "F1"})
			doc.append("es_invoice_series", {"series": SERIES_R1, "invoice_type": "R1"})
		doc.save()
		frappe.clear_document_cache("Company", self.company)

	def invoice(self, rate: float = 100, **extra):
		return frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"naming_series": "ACC-SINV-.YYYY.-",
				"debit_to": pgc.account_by_number(self.company, "4300"),
				"cost_center": self.cost_center,
				"due_date": add_days(nowdate(), 30),
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"rate": rate,
						"income_account": pgc.account_by_number(self.company, "7050"),
						"cost_center": self.cost_center,
					}
				],
				**extra,
			}
		)


class TestFiscalNumbering(BillingTestCase):
	def test_draft_name_then_fiscal_number(self):
		"""Criterio 1: borrador con nombre temporal; al validar, el siguiente de la serie."""
		self.configure()
		si = self.invoice().insert()
		self.assertTrue(si.name.startswith("BORR-"), si.name)
		si.submit()
		self.assertTrue(si.name.startswith(f"FN-{self.abbr}-"), si.name)
		self.assertEqual(str(si.posting_date), nowdate())
		self.assertTrue(frappe.get_all("GL Entry", filters={"voucher_no": si.name}))
		self.assertFalse(frappe.db.exists("Sales Invoice", {"name": ["like", "BORR-%"], "docstatus": 1}))

	def test_consecutive_and_failure_does_not_consume(self):
		"""Criterio 5: consecutivos en orden de validación; un fallo no consume número."""
		self.configure()
		first = self.invoice().insert()
		second = self.invoice().insert()
		third = self.invoice().insert()
		first.submit()

		frappe.db.savepoint("second_submit")
		with unittest.mock.patch(
			"erpnext.accounts.doctype.sales_invoice.sales_invoice.SalesInvoice.make_gl_entries",
			side_effect=frappe.ValidationError("fallo simulado"),
		):
			with self.assertRaises(frappe.ValidationError):
				second.submit()
		frappe.db.rollback(save_point="second_submit")

		third.reload()
		third.submit()
		number = lambda name: int(name.rsplit("-", 1)[1])  # noqa: E731
		self.assertEqual(number(third.name), number(first.name) + 1)

	def test_without_numbering_uses_naming_series(self):
		"""Criterio 2."""
		self.configure(numbering=False)
		si = self.invoice().insert()
		self.assertTrue(si.name.startswith("ACC-SINV-"), si.name)
		si.submit()
		self.assertTrue(si.name.startswith("ACC-SINV-"), si.name)

	def test_credit_note_series_and_reason(self):
		"""Criterio 3: la R1 recibe su serie; sin tipo R ni motivo no se valida."""
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		self.configure()
		original = self.invoice().insert()
		original.submit()
		credit = make_sales_return(original.name)
		credit.es_invoice_type = "F1"
		credit.insert()
		with self.assertRaisesRegex(frappe.ValidationError, "R1 a R5"):
			credit.submit()
		credit.reload()
		credit.es_invoice_type = "R1"
		credit.es_rectification_reason = ""
		credit.save()
		with self.assertRaisesRegex(frappe.ValidationError, "motivo"):
			credit.submit()
		credit.reload()
		credit.es_rectification_reason = "Devolución de la mercancía"
		credit.save()
		credit.submit()
		self.assertTrue(credit.name.startswith(f"RN-{self.abbr}-"), credit.name)
		self.assertEqual(credit.es_rectification_method, "Por diferencias")

	def test_amend_blocked(self):
		"""Criterio 4."""
		self.configure()
		si = self.invoice().insert()
		si.submit()
		si.reload()
		si.cancel()
		amended = frappe.copy_doc(si)
		amended.amended_from = si.name
		amended.docstatus = 0
		with self.assertRaisesRegex(frappe.ValidationError, "rectificativa"):
			amended.insert()


class TestCollectionStatus(BillingTestCase):
	def setUp(self):
		self.configure(numbering=False)

	def balance(self, number: str, party: bool = True) -> float:
		filters = {"account": pgc.account_by_number(self.company, number), "is_cancelled": 0}
		if party:
			filters["party"] = self.customer
		rows = frappe.get_all("GL Entry", filters=filters, fields=["debit", "credit"])
		return flt(sum(r.debit - r.credit for r in rows))

	def receivable_total(self) -> float:
		from erpnext.accounts.report.accounts_receivable.accounts_receivable import execute

		_columns, data, *_ = execute(
			frappe._dict(
				company=self.company,
				report_date=nowdate(),
				party_type="Customer",
				party=[self.customer],
				ageing_based_on="Due Date",
				range="30, 60, 90, 120",
			)
		)
		return flt(
			sum(
				row.get("outstanding") or 0 for row in data if isinstance(row, dict) and row.get("voucher_no")
			)
		)

	def test_doubtful_impairment_loss(self):
		"""Criterio 6: dudoso cobro, deterioro y pérdida con sus asientos."""
		before_4300, before_4360 = self.balance("4300"), self.balance("4360")
		si = self.invoice(rate=1000).insert()
		si.submit()
		receivable_before = self.receivable_total()

		collection.mark_doubtful(si.name)
		si.reload()
		self.assertEqual(si.es_collection_status, "Dudoso cobro")
		self.assertAlmostEqual(si.outstanding_amount, 0)
		self.assertAlmostEqual(self.balance("4300") - before_4300, 0)
		self.assertAlmostEqual(self.balance("4360") - before_4360, 1000)
		self.assertAlmostEqual(
			self.receivable_total(), receivable_before
		)  # el cliente sigue debiendo lo mismo

		collection.provision_impairment(si.name)
		si.reload()
		self.assertAlmostEqual(si.es_impairment_amount, 1000)

		collection.declare_loss(si.name)
		si.reload()
		self.assertEqual(si.es_collection_status, "Pérdida")
		self.assertAlmostEqual(self.balance("4360") - before_4360, 0)
		loss = frappe.get_doc("Journal Entry", si.es_loss_entry)
		numbers = {frappe.db.get_value("Account", r.account, "account_number"): r for r in loss.accounts}
		self.assertAlmostEqual(numbers["6500"].debit, 1000)
		self.assertAlmostEqual(numbers["4900"].debit, 1000)
		self.assertAlmostEqual(numbers["7940"].credit, 1000)

	def test_recover(self):
		before_4300 = self.balance("4300")
		si = self.invoice(rate=500).insert()
		si.submit()
		collection.mark_doubtful(si.name)
		collection.recover(si.name)
		si.reload()
		self.assertEqual(si.es_collection_status, "Normal")
		self.assertAlmostEqual(si.outstanding_amount, 500)
		self.assertAlmostEqual(self.balance("4300") - before_4300, 500)

	def test_requires_role(self):
		si = self.invoice().insert()
		si.submit()
		user = "es-collection-test@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Cobros"}).insert()
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				collection.mark_doubtful(si.name)
		finally:
			frappe.set_user("Administrator")


class TestNonPgcUnchanged(IntegrationTestCase):
	def test_validate_does_nothing_without_numbering(self):
		"""Criterio 8: sin numeración fiscal no se exige nada."""
		from erpnext_spain.es_facturacion import numbering

		other = make_company("_Test ES Facturación sin PGC", "_TEFS")
		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": other,
				"is_return": 1,
				"amended_from": "X",
				"docstatus": 1,
			}
		)
		numbering.validate(doc)
		numbering.before_submit(doc)


class TestPrintFormat(BillingTestCase):
	def render(self, doc) -> str:
		from erpnext_spain.es_verifactu.printing import FORMAT_NAME

		html = frappe.db.get_value("Print Format", FORMAT_NAME, "html")
		return frappe.render_template(html, {"doc": doc})

	def test_breakdown_withholding_and_no_qr_without_verifactu(self):
		from erpnext_spain.es_facturacion.printing import tax_summary
		from erpnext_spain.es_impuestos import initial_data
		from erpnext_spain.es_impuestos.tests.test_initial_data import apply_template

		self.configure(numbering=False)
		si = self.invoice(
			rate=1000,
			taxes_and_charges=initial_data.template_name(
				self.company, "Sales Taxes and Charges Template", "IVA 21 % con retención 15 %"
			),
		)
		apply_template(si)
		si.insert()
		si.submit()
		summary = tax_summary(si)
		self.assertEqual([(r["tax_type"], r["rate"]) for r in summary["vat"]], [("IVA", 21)])
		self.assertAlmostEqual(summary["vat"][0]["base"], 1000)
		self.assertAlmostEqual(summary["vat"][0]["amount"], 210)
		self.assertAlmostEqual(summary["withholding"][0]["amount"], -150)
		html = self.render(si)
		self.assertIn("Retención IRPF", html)
		self.assertIn("Total a pagar", html)
		self.assertNotIn('<div class="bloque-verifactu">', html)

	def test_exempt_mention_and_rectified_reference(self):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		from erpnext_spain.es_impuestos import initial_data
		from erpnext_spain.es_impuestos.tests.test_initial_data import apply_template

		self.configure()
		si = self.invoice(
			taxes_and_charges=initial_data.template_name(
				self.company, "Sales Taxes and Charges Template", "Entrega intracomunitaria"
			)
		)
		apply_template(si)
		si.insert()
		si.submit()
		self.assertIn("Entrega intracomunitaria exenta", self.render(si))

		credit = make_sales_return(si.name)
		credit.es_invoice_type = "R1"
		credit.es_rectification_reason = "Error en el precio"
		credit.insert()
		credit.submit()
		html = self.render(credit)
		self.assertIn("Factura rectificativa", html)
		self.assertIn(si.name, html)
		self.assertIn("Error en el precio", html)
