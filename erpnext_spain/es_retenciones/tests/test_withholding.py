# Retenciones practicadas y soportadas (spec 08, criterios 1-6 y 8-10).

import zlib

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_impuestos import initial_data
from erpnext_spain.es_impuestos.tests.test_initial_data import apply_template, ensure_item, make_company
from erpnext_spain.es_retenciones import codes
from erpnext_spain.es_retenciones.setup import setup_company

NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def nif(seed: str) -> str:
	"""NIF válido y estable para cada nombre de proveedor de test."""
	number = zlib.crc32(seed.encode()) % 100_000_000
	return f"{number:08d}{NIF_LETTERS[number % 23]}"


class TestWithholdingsMade(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Retenciones", "_TERE")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.service = ensure_item("_Test ES Servicio profesional")
		cls.outlay = ensure_item("_Test ES Suplido")

	def supplier(self, name: str, category: str | None = codes.PROFESSIONAL, group: str | None = None) -> str:
		if not frappe.db.exists("Supplier", name):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": name,
					"tax_id": nif(name),
					"tax_withholding_category": category,
					"tax_withholding_group": group,
				}
			).insert()
		return name

	def purchase_invoice(self, supplier: str, lines=((None, 1000, True),), posting_date=None, **extra):
		category = frappe.db.get_value("Supplier", supplier, "tax_withholding_category")
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": supplier,
				"posting_date": posting_date or nowdate(),
				"set_posting_time": 1,
				"bill_no": frappe.generate_hash(length=8),
				"credit_to": pgc.account_by_number(self.company, "4100"),
				"cost_center": self.cost_center,
				"apply_tds": 1,
				"items": [
					{
						"item_code": item or self.service,
						"qty": 1,
						"rate": rate,
						"apply_tds": 1 if tds else 0,
						"tax_withholding_category": category if tds else None,
						"expense_account": pgc.account_by_number(self.company, "6230"),
						"cost_center": self.cost_center,
					}
					for item, rate, tds in lines
				],
				"taxes_and_charges": initial_data.template_name(
					self.company, "Purchase Taxes and Charges Template", "IVA soportado 21 %"
				),
				**extra,
			}
		)
		apply_template(pi)
		return pi

	def withheld(self, pi) -> float:
		return sum(t.tax_amount for t in pi.taxes if t.is_tax_withholding_account)

	def test_categories_and_company_account(self):
		account = pgc.account_by_number(self.company, "4751")
		for name, spec in codes.CATEGORIES.items():
			doc = frappe.get_doc("Tax Withholding Category", name)
			self.assertEqual(doc.es_tax_model, spec["model"])
			self.assertEqual(doc.tax_deduction_basis, "Net Total")
			self.assertFalse(any(r.single_threshold or r.cumulative_threshold for r in doc.rates))
			self.assertIn((self.company, account), [(r.company, r.account) for r in doc.accounts])
		self.assertEqual(setup_company(self.company), [])  # idempotente

	def test_professional_15(self):
		"""Criterio 1: 1.000 € + 21 % - 15 % = 1.060 €; 150 € en la 4751; entrada con NIF."""
		supplier = self.supplier("_Test ES Profesional")
		pi = self.purchase_invoice(supplier).insert()
		pi.submit()
		self.assertAlmostEqual(pi.grand_total, 1060)
		self.assertAlmostEqual(self.withheld(pi), 150)
		row = next(t for t in pi.taxes if t.is_tax_withholding_account)
		self.assertEqual(row.account_head, pgc.account_by_number(self.company, "4751"))
		self.assertEqual(row.es_tax_type, "Retención IRPF")
		self.assertEqual(row.es_withholding_key, "Actividades profesionales")
		entry = pi.tax_withholding_entries[0]
		self.assertAlmostEqual(entry.taxable_amount, 1000)
		self.assertAlmostEqual(entry.withholding_amount, 150)
		self.assertEqual(entry.tax_id, frappe.db.get_value("Supplier", supplier, "tax_id"))

	def test_start_of_activity_7(self):
		"""Criterio 2."""
		supplier = self.supplier("_Test ES Profesional nuevo", group=codes.GROUP_START)
		pi = self.purchase_invoice(supplier).insert()
		self.assertAlmostEqual(self.withheld(pi), 70)

	def test_outlay_line_excluded(self):
		"""Criterio 3: la línea de suplido sin apply_tds no entra en la base."""
		supplier = self.supplier("_Test ES Profesional con suplidos")
		pi = self.purchase_invoice(supplier, lines=((None, 1000, True), (self.outlay, 200, False))).insert()
		self.assertAlmostEqual(self.withheld(pi), 150)

	def test_leasing_requires_property(self):
		"""Criterio 4: arrendamiento al 19 %, modelo 115, sin inmueble no se valida."""
		supplier = self.supplier("_Test ES Arrendador", category=codes.LEASING)
		pi = self.purchase_invoice(supplier).insert()
		self.assertAlmostEqual(self.withheld(pi), 190)
		self.assertEqual(
			frappe.db.get_value("Tax Withholding Category", codes.LEASING, "es_tax_model"), "115"
		)
		with self.assertRaisesRegex(frappe.ValidationError, "inmueble"):
			pi.submit()
		pi.reload()
		pi.es_leased_property = (
			frappe.get_doc(
				{
					"doctype": "ES Leased Property",
					"title": "Local de prueba",
					"company": self.company,
					"lessor": supplier,
					"situation": codes.PROPERTY_SITUATIONS[0],
					"cadastral_reference": "9872023 VH5797S 0001 WX",
					"address": "Calle Mayor 1, Madrid",
				}
			)
			.insert()
			.name
		)
		pi.submit()
		self.assertEqual(pi.docstatus, 1)

	def test_rate_change_by_date(self):
		"""Criterio 5: cada factura toma el tipo vigente en su fecha."""
		category = frappe.get_doc("Tax Withholding Category", codes.PROFESSIONAL)
		change = add_days(nowdate(), -10)
		general = next(r for r in category.rates if not r.tax_withholding_group)
		general.to_date = add_days(change, -1)
		category.append("rates", {"tax_withholding_rate": 17, "from_date": change, "to_date": codes.TO_DATE})
		category.save()
		supplier = self.supplier("_Test ES Profesional cambio")
		before = self.purchase_invoice(supplier, posting_date=add_days(change, -5)).insert()
		after = self.purchase_invoice(supplier, posting_date=change).insert()
		self.assertAlmostEqual(self.withheld(before), 150)
		self.assertAlmostEqual(self.withheld(after), 170)

	def test_debit_note_reverses(self):
		"""Criterio 6: la rectificativa de compra revierte la retención."""
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

		supplier = self.supplier("_Test ES Profesional rectificada")
		pi = self.purchase_invoice(supplier).insert()
		pi.submit()
		note = make_debit_note(pi.name)
		note.bill_no = frappe.generate_hash(length=8)
		note.insert()
		note.submit()
		self.assertAlmostEqual(self.withheld(note), -150)

	def test_advance_then_invoice_no_double_withholding(self):
		"""Criterio 7: anticipo con retención y factura posterior: se retiene una sola vez."""
		supplier = self.supplier("_Test ES Profesional anticipo")
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Pay",
				"company": self.company,
				"party_type": "Supplier",
				"party": supplier,
				"paid_from": pgc.account_by_number(self.company, "5720"),
				"paid_to": pgc.account_by_number(self.company, "4100"),
				"paid_amount": 1000,
				"received_amount": 1000,
				"reference_no": "ANT-1",
				"reference_date": nowdate(),
				"apply_tds": 1,
				"tax_withholding_category": codes.PROFESSIONAL,
				"cost_center": self.cost_center,
			}
		)
		pe.insert()
		withholding_rows = [t for t in pe.taxes if t.is_tax_withholding_account]
		self.assertTrue(withholding_rows)
		self.assertEqual(withholding_rows[0].es_tax_type, "Retención IRPF")
		pe.submit()

		pi = self.purchase_invoice(supplier)
		pi.allocate_advances_automatically = 1
		pi.insert()
		pi.submit()
		entries = frappe.get_all(
			"Tax Withholding Entry",
			filters={"party": supplier, "status": ["not in", ["Cancelled", "Duplicate"]], "docstatus": 1},
			fields=["withholding_amount", "taxable_amount", "status"],
		)
		self.assertAlmostEqual(sum(e.withholding_amount for e in entries), 150, msg=entries)

	def test_supplier_group_without_rate_rejected(self):
		"""Criterio 9."""
		with self.assertRaisesRegex(frappe.ValidationError, "no tiene tipo para el grupo"):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": "_Test ES Consejero mal agrupado",
					"tax_withholding_category": codes.DIRECTORS,
					"tax_withholding_group": codes.GROUP_START,
				}
			).insert()

	def test_non_pgc_company_untouched(self):
		"""Criterio 10: en una compañía sin PGC no se crean filas de cuenta ni se clasifica."""
		from erpnext_spain.es_retenciones.withholding import validate_purchase_invoice

		other = make_company("_Test ES Retenciones sin PGC", "_TERS")
		doc = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": other,
				"apply_tds": 1,
				"taxes": [{"is_tax_withholding_account": 1, "account_head": "x"}],
			}
		)
		validate_purchase_invoice(doc)
		self.assertFalse(doc.taxes[0].es_tax_type)
		for name in codes.CATEGORIES:
			companies = frappe.get_all("Tax Withholding Account", filters={"parent": name}, pluck="company")
			self.assertNotIn(other, companies)

	def test_made_report(self):
		from erpnext_spain.es_retenciones.report.es_withholdings_made.es_withholdings_made import execute

		supplier = self.supplier("_Test ES Profesional informe")
		pi = self.purchase_invoice(supplier).insert()
		pi.submit()
		_columns, rows = execute({"company": self.company, "party": supplier})
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].tax_model, "111")
		self.assertAlmostEqual(rows[0].taxable_amount, 1000)
		self.assertAlmostEqual(rows[0].withholding_amount, 150)
		self.assertEqual(rows[0].tax_id, frappe.db.get_value("Supplier", supplier, "tax_id"))

	def test_received_report(self):
		from erpnext_spain.es_impuestos.tests.test_initial_data import ensure_party
		from erpnext_spain.es_retenciones.report.es_withholdings_received.es_withholdings_received import (
			execute,
		)

		customer = ensure_party("Customer", "_Test ES Cliente que retiene")
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": customer,
				"debit_to": pgc.account_by_number(self.company, "4300"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.service,
						"qty": 1,
						"rate": 1000,
						"income_account": pgc.account_by_number(self.company, "7050"),
						"cost_center": self.cost_center,
					}
				],
				"taxes_and_charges": initial_data.template_name(
					self.company, "Sales Taxes and Charges Template", "IVA 21 % con retención 15 %"
				),
			}
		)
		apply_template(si)
		si.insert()
		si.submit()
		_columns, rows = execute({"company": self.company, "customer": customer})
		self.assertEqual(len(rows), 1)
		self.assertAlmostEqual(rows[0].withholding_amount, 150)
		self.assertAlmostEqual(rows[0].taxable_amount, 1000)
		self.assertEqual(rows[0].rate, 15)

	def test_sales_credit_note_reverses_withholding(self):
		"""Criterio 8: la rectificativa de una venta con retención invierte el cargo en la 473."""
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		from erpnext_spain.es_impuestos.tests.test_initial_data import ensure_party

		customer = ensure_party("Customer", "_Test ES Cliente que retiene")
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": customer,
				"debit_to": pgc.account_by_number(self.company, "4300"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.service,
						"qty": 1,
						"rate": 1000,
						"income_account": pgc.account_by_number(self.company, "7050"),
						"cost_center": self.cost_center,
					}
				],
				"taxes_and_charges": initial_data.template_name(
					self.company, "Sales Taxes and Charges Template", "IVA 21 % con retención 15 %"
				),
			}
		)
		apply_template(si)
		si.insert()
		si.submit()
		credit = make_sales_return(si.name)
		credit.insert()
		credit.submit()
		self.assertAlmostEqual(credit.grand_total, -1060)
		gl = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_no": credit.name,
				"account": pgc.account_by_number(self.company, "4730"),
				"is_cancelled": 0,
			},
			fields=["debit", "credit"],
		)
		self.assertAlmostEqual(sum(r.credit - r.debit for r in gl), 150)
