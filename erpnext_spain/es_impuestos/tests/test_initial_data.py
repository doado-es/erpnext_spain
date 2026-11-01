# Tests de los datos iniciales de impuestos (specs 03 y 09).

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_impuestos import initial_data


def make_company(name: str, abbr: str) -> str:
	if not frappe.db.exists("Company", name):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": name,
				"abbr": abbr,
				"country": "Spain",
				"default_currency": "EUR",
				"chart_of_accounts": "Standard",
			}
		).insert()
	return name


def ensure_party(doctype: str, name: str, tax_category: str | None = None) -> str:
	if not frappe.db.exists(doctype, name):
		field = "customer_name" if doctype == "Customer" else "supplier_name"
		frappe.get_doc({"doctype": doctype, field: name, "tax_category": tax_category}).insert()
	return name


def ensure_item(code: str, item_tax_template: str | None = None) -> str:
	if not frappe.db.exists("Item", code):
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		)
		if item_tax_template:
			doc.append("taxes", {"item_tax_template": item_tax_template})
		doc.insert()
	return code


def apply_template(doc) -> None:
	"""Lo que hace el formulario al elegir la plantilla: copia sus líneas."""
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	doctype = doc.meta.get_field("taxes_and_charges").options
	doc.set("taxes", get_taxes_and_charges(doctype, doc.taxes_and_charges))


class TestTaxInitialData(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Impuestos", "_TEI")
		pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.item = ensure_item("_Test ES Servicio IVA")

	def template(self, doctype: str, title: str) -> str:
		return initial_data.template_name(self.company, doctype, title)

	def gl(self, voucher_type: str, voucher_no: str) -> dict[str, float]:
		rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
			fields=["account", "debit", "credit"],
		)
		balances = {}
		for row in rows:
			number = frappe.db.get_value("Account", row.account, "account_number")
			balances[number] = balances.get(number, 0) + row.debit - row.credit
		return balances

	def sales_invoice(
		self, template: str, rate: float = 1000, item: str | None = None, customer: str | None = None
	):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": customer or ensure_party("Customer", "_Test ES Impuestos Cliente"),
				"debit_to": pgc.account_by_number(self.company, "4300"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": item or self.item,
						"qty": 1,
						"rate": rate,
						"income_account": pgc.account_by_number(self.company, "7050"),
						"cost_center": self.cost_center,
					}
				],
				"taxes_and_charges": self.template("Sales Taxes and Charges Template", template),
			}
		)
		apply_template(si)
		si.insert()
		si.submit()
		return si

	def test_records_created(self):
		company = self.company
		self.assertEqual(
			frappe.db.count("Sales Taxes and Charges Template", {"company": company}),
			len(initial_data.SALES_TEMPLATES),
		)
		self.assertEqual(
			frappe.db.count("Purchase Taxes and Charges Template", {"company": company}),
			len(initial_data.PURCHASE_TEMPLATES),
		)
		self.assertEqual(
			frappe.db.count("Item Tax Template", {"company": company}), len(initial_data.ITEM_TAX_TEMPLATES)
		)
		self.assertEqual(
			frappe.db.count("Tax Rule", {"company": company}),
			len(initial_data.SALES_RULES) + len(initial_data.PURCHASE_RULES),
		)
		for name in initial_data.TAX_CATEGORIES:
			self.assertTrue(frappe.db.exists("Tax Category", name))
		self.assertTrue(frappe.db.exists("Account", {"company": company, "account_number": "4771"}))
		self.assertEqual(
			frappe.db.get_value("Company", company, "es_initial_data_version"), initial_data.DATA_VERSION
		)
		default = frappe.db.get_value(
			"Sales Taxes and Charges Template", {"company": company, "is_default": 1}, "title"
		)
		self.assertEqual(default, "IVA 21 %")
		transfer = frappe.db.get_value(
			"Mode of Payment Account", {"parent": "Wire Transfer", "company": company}, "default_account"
		)
		self.assertEqual(frappe.db.get_value("Account", transfer, "account_number"), "5720")

	def test_template_rows_are_classified(self):
		doc = frappe.get_doc(
			"Sales Taxes and Charges Template",
			self.template("Sales Taxes and Charges Template", "Entrega intracomunitaria"),
		)
		self.assertEqual(doc.taxes[0].es_tax_type, "IVA")
		self.assertEqual(doc.taxes[0].es_vat_classification, "E5")
		self.assertEqual(doc.taxes[0].es_operation_type, "Entrega intracomunitaria")

	def test_idempotent_and_respects_user_changes(self):
		name = self.template("Sales Taxes and Charges Template", "IVA 10 %")
		frappe.db.set_value("Sales Taxes and Charges", {"parent": name}, "rate", 9)
		created = initial_data.ensure_company_records(self.company)
		self.assertTrue(all(not value for value in created.values()), created)
		self.assertEqual(frappe.db.get_value("Sales Taxes and Charges", {"parent": name}, "rate"), 9)

	def test_sales_with_withholding(self):
		"""Spec 08, criterio 8: 1.000 € + IVA 21 % - retención 15 % = 1.060 €; cargo de 150 € en la 473."""
		si = self.sales_invoice("IVA 21 % con retención 15 %")
		self.assertAlmostEqual(si.grand_total, 1060)
		self.assertAlmostEqual(si.outstanding_amount, 1060)
		gl = self.gl("Sales Invoice", si.name)
		self.assertAlmostEqual(gl["4730"], 150)
		self.assertAlmostEqual(gl["4770"], -210)
		self.assertAlmostEqual(gl["4300"], 1060)
		# La clasificación de la plantilla llega a la factura.
		self.assertEqual([t.es_tax_type for t in si.taxes], ["IVA", "Retención IRPF"])

	def test_item_tax_template_changes_rate(self):
		reduced = initial_data.template_name(self.company, "Item Tax Template", "IVA 10 %")
		item = ensure_item("_Test ES Artículo IVA 10", reduced)
		si = self.sales_invoice("IVA 21 %", item=item)
		self.assertAlmostEqual(si.total_taxes_and_charges, 100)

	def test_intra_community_acquisition_self_assessed(self):
		"""Spec 06, criterio 6: la autorrepercusión deja 210 € en la 4720 y 210 € en la 4770."""
		supplier = ensure_party(
			"Supplier", "_Test ES Impuestos Proveedor UE", initial_data.INTRA_EU_PURCHASES
		)
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": supplier,
				"credit_to": pgc.account_by_number(self.company, "4000"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"rate": 1000,
						"expense_account": pgc.account_by_number(self.company, "6000"),
						"cost_center": self.cost_center,
					}
				],
				"taxes_and_charges": self.template(
					"Purchase Taxes and Charges Template", "Adquisición intracomunitaria de bienes 21 %"
				),
			}
		)
		apply_template(pi)
		pi.insert()
		pi.submit()
		self.assertAlmostEqual(pi.grand_total, 1000)
		gl = self.gl("Purchase Invoice", pi.name)
		self.assertAlmostEqual(gl["4720"], 210)
		self.assertAlmostEqual(gl["4770"], -210)
		self.assertAlmostEqual(gl["4000"], -1000)
		self.assertEqual([t.es_self_assessed for t in pi.taxes], [0, 1])

	def test_rows_of_non_pgc_companies_not_mirrored(self):
		"""Solo se replican plantillas de compañías con PGC (R7)."""
		other = make_company("_Test ES Impuestos sin PGC", "_TEISP")
		group = frappe.db.get_value(
			"Account", {"company": other, "is_group": 1, "account_type": "Tax"}
		) or frappe.db.get_value("Account", {"company": other, "is_group": 1, "root_type": "Liability"})
		account = frappe.db.get_value("Account", {"company": other, "account_name": "_Test IVA otro"}) or (
			frappe.get_doc(
				{
					"doctype": "Account",
					"company": other,
					"account_name": "_Test IVA otro",
					"parent_account": group,
					"account_type": "Tax",
				}
			)
			.insert()
			.name
		)
		template = frappe.db.get_value(
			"Item Tax Template", {"company": other, "title": "_Test IVA otro"}
		) or (
			frappe.get_doc(
				{
					"doctype": "Item Tax Template",
					"company": other,
					"title": "_Test IVA otro",
					"taxes": [{"tax_type": account, "tax_rate": 10}],
				}
			)
			.insert()
			.name
		)
		item = frappe.get_doc("Item", ensure_item("_Test ES Artículo de otra compañía", template))
		item.save()
		self.assertEqual([row.tax_category or "" for row in item.taxes], [""])

	def test_reduced_item_rows_mirrored(self):
		"""La fila sin categoría del artículo se replica para recargo, retención y
		adquisición intracomunitaria, sin duplicarse al volver a guardar."""
		reduced = self.template("Item Tax Template", "IVA 10 %")
		item = frappe.get_doc("Item", ensure_item("_Test ES Artículo IVA 10 categorías", reduced))
		item.save()
		categories = sorted(row.tax_category or "" for row in item.taxes)
		self.assertEqual(
			categories,
			sorted(
				[
					"",
					initial_data.NATIONAL_RE,
					initial_data.NATIONAL_WITHHOLDING,
					initial_data.INTRA_EU_PURCHASES,
				]
			),
		)

	def reduced_purchase(self, supplier: str, template: str):
		reduced = self.template("Item Tax Template", "IVA 10 %")
		item = ensure_item("_Test ES Artículo IVA 10 compras", reduced)
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": supplier,
				"credit_to": pgc.account_by_number(self.company, "4000"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": item,
						"qty": 1,
						"rate": 1000,
						"expense_account": pgc.account_by_number(self.company, "6000"),
						"cost_center": self.cost_center,
					}
				],
				"taxes_and_charges": self.template("Purchase Taxes and Charges Template", template),
			}
		)
		apply_template(pi)
		pi.insert()
		return pi

	def test_reduced_item_for_surcharge_customer(self):
		"""Cliente con recargo: el artículo al 10 % lleva 10 % de IVA y 1,4 % de recargo."""
		reduced = self.template("Item Tax Template", "IVA 10 %")
		item = ensure_item("_Test ES Artículo IVA 10 recargo", reduced)
		customer = ensure_party("Customer", "_Test ES Impuestos Cliente RE", initial_data.NATIONAL_RE)
		si = self.sales_invoice("IVA 21 % + RE 5,2 %", item=item, customer=customer)
		self.assertEqual(si.tax_category, initial_data.NATIONAL_RE)
		self.assertAlmostEqual(si.total_taxes_and_charges, 114)

	def test_reduced_item_intra_eu_purchase_and_sale(self):
		"""Compra intracomunitaria: se autoliquida al 10 %. Venta: sigue exenta."""
		supplier = ensure_party(
			"Supplier", "_Test ES Impuestos Proveedor UE", initial_data.INTRA_EU_PURCHASES
		)
		pi = self.reduced_purchase(supplier, "Adquisición intracomunitaria de bienes 21 %")
		self.assertEqual([row.tax_amount for row in pi.taxes], [100, 100])

		reduced = self.template("Item Tax Template", "IVA 10 %")
		item = ensure_item("_Test ES Artículo IVA 10 ventas UE", reduced)
		customer = ensure_party("Customer", "_Test ES Impuestos Cliente UE", initial_data.INTRA_EU_SALES)
		si = self.sales_invoice("Entrega intracomunitaria", item=item, customer=customer)
		self.assertAlmostEqual(si.total_taxes_and_charges, 0)

	def test_tax_rule_picks_template_by_category(self):
		"""Spec 03, criterio 2: al elegir un cliente intracomunitario, la factura recibe
		la plantilla de entrega intracomunitaria (lo mismo que hace el formulario)."""
		from erpnext.accounts.party import get_party_details

		customer = ensure_party("Customer", "_Test ES Impuestos Cliente UE", initial_data.INTRA_EU_SALES)
		details = get_party_details(customer, "Customer", company=self.company, doctype="Sales Invoice")
		self.assertEqual(
			details.get("taxes_and_charges"),
			self.template("Sales Taxes and Charges Template", "Entrega intracomunitaria"),
		)
