# Categoría de impuestos por país en direcciones y proveedores (es_impuestos/tax_category.py).

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_impuestos import tax_category
from erpnext_spain.es_impuestos.initial_data import (
	EXTRA_EU,
	INTRA_EU,
	NATIONAL,
	NATIONAL_RE,
	SPECIAL_TERRITORIES,
	ensure_global_records,
)


class TestTaxCategoryByCountry(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_global_records()

	def test_rule(self):
		self.assertEqual(tax_category.category_for("Spain", "15705"), NATIONAL)
		for postcode in ("35001", "38001", "51001", "52001"):
			self.assertEqual(tax_category.category_for("Spain", postcode), SPECIAL_TERRITORIES, postcode)
		self.assertEqual(tax_category.category_for("France", None, "FR40303265045"), INTRA_EU)
		self.assertEqual(tax_category.category_for("France", None, None), NATIONAL)  # consumidor final
		self.assertEqual(tax_category.category_for("United States", None, "12-3456789"), EXTRA_EU)
		self.assertIsNone(tax_category.category_for(None))

	def test_no_default_category(self):
		"""Sin valor por defecto: vacío equivale a nacional (IVA reducido de los artículos)."""
		for doctype in ("Customer", "Supplier"):
			self.assertFalse(frappe.new_doc(doctype).tax_category, doctype)

	def address(self, customer: str, country: str, pincode: str = "15705"):
		return frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": customer,
				"address_line1": "Rúa Nova 1",
				"city": "Ames",
				"pincode": pincode,
				"country": country,
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		).insert()

	def test_address_category(self):
		"""«Nacional» queda vacío en la dirección: manda la del cliente (p. ej. recargo)."""
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "Client Exemple SARL", "tax_id": "FR40303265045"}
		).insert()
		address = self.address(customer.name, "France", "75001")
		self.assertEqual(address.tax_category, INTRA_EU)

		address.tax_category = EXTRA_EU  # a mano, mismo país: se respeta
		address.save()
		self.assertEqual(address.tax_category, EXTRA_EU)

		address.country, address.pincode = "Spain", "38001"
		address.save()
		self.assertEqual(address.tax_category, SPECIAL_TERRITORIES)

		address.pincode = "15705"
		address.save()
		self.assertFalse(address.tax_category)

	def test_supplier_category(self):
		supplier = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "Lieferant Beispiel GmbH",
				"country": "Germany",
				"tax_id": "DE136695976",
			}
		).insert()
		self.assertEqual(supplier.tax_category, INTRA_EU)

		supplier.tax_category = NATIONAL_RE  # a mano, mismo país: se respeta
		supplier.save()
		self.assertEqual(supplier.tax_category, NATIONAL_RE)

		supplier.country = "United States"
		supplier.save()
		self.assertEqual(supplier.tax_category, EXTRA_EU)

		supplier.country, supplier.tax_id = "Spain", "B58834813"  # nacional: vacío
		supplier.save()
		self.assertFalse(supplier.tax_category)

		# Nuevo y español con una categoría elegida a mano: se respeta.
		retailer = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "Proveedor Minorista SL",
				"country": "Spain",
				"tax_category": NATIONAL_RE,
			}
		).insert()
		self.assertEqual(retailer.tax_category, NATIONAL_RE)
