# Desglose fiscal sobre la marcha, libros y contrato con VeriFactu (spec 06, criterios 1-9).

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, get_first_day, get_last_day, nowdate

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company
from erpnext_spain.es_impuestos import initial_data
from erpnext_spain.es_impuestos.tests.test_initial_data import apply_template, ensure_item, ensure_party
from erpnext_spain.es_iva import books, rows


class VatTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Registro IVA", "_TERI")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.item = ensure_item("_Test ES Artículo IVA general")
		reduced = initial_data.template_name(cls.company, "Item Tax Template", "IVA 10 %")
		cls.reduced_item = ensure_item("_Test ES Artículo IVA reducido " + cls.company, reduced)
		cls.customer = ensure_party("Customer", "_Test ES Cliente Registro")
		cls.supplier = ensure_party("Supplier", "_Test ES Proveedor Registro")
		cls.period = {
			"company": cls.company,
			"from_date": get_first_day(nowdate()),
			"to_date": get_last_day(nowdate()),
		}

	def setUp(self):
		frappe.db.set_value("Company", self.company, "es_vat_pro_rata", 0)
		frappe.clear_document_cache("Company", self.company)

	def template(self, doctype: str, title: str) -> str:
		return initial_data.template_name(self.company, doctype, title)

	def sale(self, lines=((None, 1000),), template="IVA 21 %", submit=True, **extra):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"debit_to": pgc.account_by_number(self.company, "4300"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": item or self.item,
						"qty": 1,
						"rate": rate,
						"income_account": pgc.account_by_number(self.company, "7000"),
						"cost_center": self.cost_center,
					}
					for item, rate in lines
				],
				"taxes_and_charges": self.template("Sales Taxes and Charges Template", template),
				**extra,
			}
		)
		apply_template(si)
		si.insert()
		if submit:
			si.submit()
		return si

	def purchase(self, template: str, rate: float = 1000):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": self.supplier,
				"bill_no": frappe.generate_hash(length=8),
				"bill_date": nowdate(),
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
				"taxes_and_charges": self.template("Purchase Taxes and Charges Template", template),
			}
		)
		apply_template(pi)
		pi.insert()
		pi.submit()
		return pi

	def rows(self, doc, **filters):
		"""Filas del desglose de la factura (validada), filtradas por campo."""
		doc = frappe.get_doc(doc.doctype, doc.name)
		result = [r for r in rows.invoice_rows(doc) if all(r.get(k) == v for k, v in filters.items())]
		return sorted(result, key=lambda r: (-r.tax_rate, r.self_assessed))

	def gl(self, doc, number: str) -> float:
		rows = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_no": doc.name,
				"account": pgc.account_by_number(self.company, number),
				"is_cancelled": 0,
			},
			fields=["debit", "credit"],
		)
		return flt(sum(r.debit - r.credit for r in rows), 2)

	def draft_totals(self) -> tuple[float, float, float]:
		rows = books.return_draft(frappe._dict(self.period))
		value = {row["concept"]: flt(row.get("tax_amount")) for row in rows}
		return (
			value["Total devengado"],
			value["Total deducible"],
			value["Resultado (borrador, no es el modelo 303)"],
		)


class TestVatRows(VatTestCase):
	def test_two_rates(self):
		"""Criterio 1: líneas al 21 % y al 10 % (Item Tax Template)."""
		si = self.sale(lines=((None, 1000), (self.reduced_item, 500)))
		rows = self.rows(si, tax_type="IVA")
		self.assertEqual(
			[(r.tax_rate, r.taxable_base, r.tax_amount) for r in rows], [(21, 1000, 210), (10, 500, 50)]
		)
		self.assertTrue(all(r.vat_classification == "S1" and r.book == "Expedidas" for r in rows))

	def test_foreign_currency_matches_gl(self):
		"""Criterio 2: venta en USD; importes en euros iguales a los del GL."""
		si = self.sale(currency="USD", conversion_rate=0.9)
		rows = self.rows(si, tax_type="IVA")
		self.assertAlmostEqual(rows[0].taxable_base, 900)
		self.assertAlmostEqual(rows[0].tax_amount, -self.gl(si, "4770"))

	def test_credit_note(self):
		"""Criterio 3: filas en negativo, tipo R1 y rectificada informada."""
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		si = self.sale()
		credit = make_sales_return(si.name)
		credit.es_invoice_type = "R1"
		credit.es_rectification_reason = "Devolución"
		credit.insert()
		credit.submit()
		row = self.rows(credit, tax_type="IVA")[0]
		self.assertAlmostEqual(row.taxable_base, -1000)
		self.assertAlmostEqual(row.tax_amount, -210)
		self.assertEqual(row.invoice_type, "R1")
		self.assertEqual(row.rectified_invoice, si.name)

	def test_cancel_excluded(self):
		"""Criterio 4: una factura cancelada deja de contar en libros y borrador."""
		accrued_before = self.draft_totals()[0]
		si = self.sale()
		self.assertAlmostEqual(self.draft_totals()[0] - accrued_before, 210)
		si.cancel()
		self.assertAlmostEqual(self.draft_totals()[0], accrued_before)
		self.assertNotIn(si.name, {r.voucher_no for r in rows.period_rows(**self.period)})

	def test_reverse_charge_purchase(self):
		"""Criterio 5: ISP 1.000 € al 21 %: 210 en 4720 y 4770; autorrepercutida y soportada; resultado 0."""
		before = self.draft_totals()
		pi = self.purchase("Inversión del sujeto pasivo 21 % (compras)")
		self.assertAlmostEqual(self.gl(pi, "4720"), 210)
		self.assertAlmostEqual(self.gl(pi, "4770"), -210)
		rows = self.rows(pi, tax_type="IVA")
		self.assertEqual(len(rows), 2)
		supported = next(r for r in rows if not r.self_assessed)
		accrued = next(r for r in rows if r.self_assessed)
		self.assertAlmostEqual(supported.tax_amount, 210)
		self.assertAlmostEqual(supported.deductible_amount, 210)
		self.assertAlmostEqual(accrued.tax_amount, 210)
		self.assertAlmostEqual(accrued.deductible_amount, 0)
		after = self.draft_totals()
		self.assertAlmostEqual(after[0] - before[0], 210)
		self.assertAlmostEqual(after[1] - before[1], 210)
		self.assertAlmostEqual(after[2] - before[2], 0)

	def test_intra_community_services(self):
		"""Criterio 6."""
		pi = self.purchase("Adquisición intracomunitaria de servicios 21 %")
		rows = self.rows(pi, tax_type="IVA")
		self.assertEqual(sorted(r.self_assessed for r in rows), [0, 1])
		self.assertTrue(all(r.operation_type == "Adquisición intracomunitaria de servicios" for r in rows))
		self.assertAlmostEqual(sum(r.tax_amount for r in rows if r.self_assessed), 210)

	def test_pro_rata(self):
		"""Criterio 7: prorrata del 60 %."""
		frappe.db.set_value("Company", self.company, "es_vat_pro_rata", 60)
		frappe.clear_document_cache("Company", self.company)
		pi = self.purchase("IVA soportado 21 %")
		row = self.rows(pi, tax_type="IVA")[0]
		self.assertAlmostEqual(row.tax_amount, 210)
		self.assertAlmostEqual(row.deductible_amount, 126)
		self.assertEqual(row.pro_rata, 60)

	def test_declared_data_frozen(self):
		"""Lo declarado no cambia con la configuración: prorrata, plantilla del artículo
		y dirección del tercero quedan congelados en la factura al validar."""
		frappe.db.set_value("Company", self.company, "es_vat_pro_rata", 60)
		frappe.clear_document_cache("Company", self.company)
		pi = self.purchase("IVA soportado 21 %")
		si = self.sale(lines=((self.reduced_item, 500),))
		before = (
			self.rows(pi, tax_type="IVA")[0].deductible_amount,
			self.rows(si, tax_type="IVA")[0].vat_classification,
		)
		frappe.db.set_value("Company", self.company, "es_vat_pro_rata", 0)
		template = frappe.db.get_value("Sales Invoice Item", {"parent": si.name}, "item_tax_template")
		previous = frappe.db.get_value("Item Tax Template", template, "es_vat_classification")
		frappe.db.set_value("Item Tax Template", template, "es_vat_classification", "E1")
		frappe.clear_cache()
		try:
			after = (
				self.rows(pi, tax_type="IVA")[0].deductible_amount,
				self.rows(si, tax_type="IVA")[0].vat_classification,
			)
		finally:
			frappe.db.set_value("Item Tax Template", template, "es_vat_classification", previous)
		self.assertEqual(before, after)
		self.assertEqual(before[0], 126)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "es_pro_rata"), 60)

	def test_books(self):
		from erpnext_spain.es_iva.report.es_issued_invoices_book.es_issued_invoices_book import execute

		si = self.sale(template="IVA 21 % con retención 15 %")
		_columns, data = execute(self.period)
		mine = [row for row in data if row.voucher_no == si.name]
		self.assertEqual([row.tax_type for row in mine], ["IVA"])  # sin retenciones
		self.assertEqual(len(self.rows(si, tax_type="Retención IRPF")), 1)  # pero registradas

	def test_verifactu_breakdown_matches_register(self):
		"""Contrato (spec 06 §6): el desglose de VeriFactu coincide con el registro."""
		from erpnext_spain.es_verifactu.utils.data_adapter import classified_tax_breakup, invoice_totals

		si = self.sale(lines=((None, 1000), (self.reduced_item, 500)), template="IVA 21 % con retención 15 %")
		breakdown = classified_tax_breakup(si)
		rows = self.rows(si, tax_type="IVA")
		self.assertEqual(
			sorted((float(b["tax_rate"]), b["taxable_base"], b["tax_amount"]) for b in breakdown),
			sorted((r.tax_rate, r.taxable_base, r.tax_amount) for r in rows),
		)
		quota, total = invoice_totals(si, breakdown)
		self.assertAlmostEqual(quota, 260)
		self.assertAlmostEqual(total, 1760)  # sin descontar la retención

	def test_surcharge_attached_to_vat_line(self):
		from erpnext_spain.es_verifactu.utils.data_adapter import build_tax_breakdown, classified_tax_breakup

		si = self.sale(template="IVA 21 % + RE 5,2 %")
		detail = build_tax_breakdown(classified_tax_breakup(si))
		self.assertEqual(len(detail), 1)
		self.assertEqual(detail[0]["TipoRecargoEquivalencia"], "5.2")
		self.assertAlmostEqual(detail[0]["CuotaRecargoEquivalencia"], 52)


class TestVatRowsNonPgc(IntegrationTestCase):
	def test_nothing_frozen_without_pgc(self):
		"""Criterio 9: en una compañía sin PGC la validación no toca la factura."""
		other = make_company("_Test ES Registro IVA sin PGC", "_TERS2")
		doc = frappe._dict(doctype="Sales Invoice", company=other, name="X", docstatus=1, items=[])
		rows.validate(doc)
		self.assertNotIn("es_party_country", doc)


class TestEffectiveRate(IntegrationTestCase):
	"""Filas de IVA de importe fijo («Actual»): el tipo sale de base y cuota."""

	def test_rate_from_base_and_amount(self):
		from erpnext_spain.es_iva.breakdown import effective_rate

		self.assertEqual(effective_rate(21, 100, 21), 21)  # con tipo, se respeta
		self.assertEqual(effective_rate(0, 1993, 418.53), 21)
		self.assertEqual(effective_rate(0, 265.66, 55.8), 21)  # cuota redondeada
		self.assertEqual(effective_rate(0, 1000, 14), 1.4)  # recargo de equivalencia
		self.assertEqual(effective_rate(0, 1000, 0), 0)
		self.assertEqual(effective_rate(0, 1000, 123), 12.3)  # sin tipo legal cercano


class TestReportsTargets(IntegrationTestCase):
	def test_report_ref_doctypes_exist(self):
		"""Los informes de la app apuntan a doctypes que existen (el borrador de
		liquidación quedó apuntando a ES Vat Register, ya borrado)."""
		for report in frappe.get_all(
			"Report", filters={"module": ["like", "ES %"]}, fields=["name", "ref_doctype"]
		):
			self.assertTrue(frappe.db.exists("DocType", report.ref_doctype), report)
