# Tests de la generación de Facturae (spec 10, criterios 1, 2, 4 y 8).

from __future__ import annotations

import hashlib

import frappe
from frappe.tests import IntegrationTestCase
from lxml import etree

from erpnext_spain.aeat.tests.helpers import clean_pem, delete_private_file, generate_p12, write_private_p12
from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_efactura import api, codes, facturae
from erpnext_spain.es_impuestos.initial_data import template_name

COMPANY = "_Test ES Facturae SL"
CIF = "B58834813"
CUSTOMER = "_Test ES Concello"
PERSON = "_Test ES Autónomo"
PASSWORD = "facturae-test"
NS = {"fe": codes.NAMESPACES["3.2.2"], "ds": "http://www.w3.org/2000/09/xmldsig#"}


def make_address(title: str, link_doctype: str, link_name: str, **extra) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": title,
			"address_type": "Billing",
			"address_line1": "Rúa do Vilar 1",
			"city": "Santiago de Compostela",
			"pincode": "15705",
			"country": "Spain",
			"links": [{"link_doctype": link_doctype, "link_name": link_name}],
			**extra,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


class TestFacturae(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		if not frappe.db.exists("Company", COMPANY):
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": COMPANY,
					"abbr": "_TEF",
					"country": "Spain",
					"default_currency": "EUR",
					"chart_of_accounts": "Standard",
					"tax_id": CIF,
				}
			).insert()
		pgc.apply_pgc_chart(COMPANY, "PYMES", dry_run=False)
		make_address(COMPANY, "Company", COMPANY, is_your_company_address=1)
		bank = "_Test ES Banco Facturae"
		if not frappe.db.exists("Bank", bank):
			frappe.get_doc({"doctype": "Bank", "bank_name": bank}).insert()
		frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": "Cuenta principal",
				"bank": bank,
				"company": COMPANY,
				"is_company_account": 1,
				"is_default": 1,
				"account": pgc.account_by_number(COMPANY, "5720"),
				"iban": "ES9121000418450200051332",
			}
		).insert()
		p12, *_ = generate_p12(password=PASSWORD.encode())
		cls.p12_url = write_private_p12("es_test_facturae.p12", p12)
		cls.addClassCleanup(delete_private_file, cls.p12_url)
		cls.addClassCleanup(clean_pem, COMPANY, "SII")
		credential = frappe.get_doc(
			{
				"doctype": "ES AEAT Credential",
				"company": COMPANY,
				"purpose": "SII",
				"cert_file": cls.p12_url,
				"cert_password": PASSWORD,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Company", COMPANY, "es_einvoice_credential", credential.name)

		if not frappe.db.exists("Customer", CUSTOMER):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": CUSTOMER,
					"tax_id": "P1500200I",
					"es_public_administration": 1,
					"es_dir3_accounting_office": "L01150020",
					"es_dir3_managing_body": "L01150020",
					"es_dir3_processing_unit": "L01150020",
				}
			).insert()
		cls.customer_address = make_address(CUSTOMER, "Customer", CUSTOMER)
		cls.cost_center = frappe.db.get_value("Company", COMPANY, "cost_center")
		if not frappe.db.exists("Item", "_Test ES Servicio Facturae"):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": "_Test ES Servicio Facturae",
					"item_group": "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 0,
				}
			).insert()

	def invoice(self, template: str = "IVA 21 %", rate: float = 1000, customer: str = CUSTOMER, **extra):
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"naming_series": "ACC-SINV-.YYYY.-",
				"company": COMPANY,
				"customer": customer,
				"customer_address": frappe.db.get_value(
					"Dynamic Link",
					{"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"},
					"parent",
				),
				"debit_to": pgc.account_by_number(COMPANY, "4300"),
				"cost_center": self.cost_center,
				"disable_rounded_total": 1,
				"items": [
					{
						"item_code": "_Test ES Servicio Facturae",
						"qty": 2,
						"rate": rate / 2,
						"income_account": pgc.account_by_number(COMPANY, "7050"),
						"cost_center": self.cost_center,
					}
				],
				"taxes_and_charges": template_name(COMPANY, "Sales Taxes and Charges Template", template),
				**extra,
			}
		)
		si.set("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", si.taxes_and_charges))
		si.insert()
		si.submit()
		return si

	def xml_of(self, e_invoice: str):
		doc = frappe.get_doc("ES E-Invoice", e_invoice)
		file = frappe.get_doc("File", {"file_url": doc.file})
		content = file.get_content()
		if isinstance(content, str):
			content = content.encode("utf-8")
		return doc, content, etree.fromstring(content)

	def test_generates_signed_valid_facturae(self):
		si = self.invoice()
		name = api.generate_facturae(si.name)
		doc, content, root = self.xml_of(name)
		facturae.validate_xml(content)  # criterio 1: valida contra el XSD oficial
		self.assertEqual(doc.status, "Generada")
		self.assertEqual(doc.file_hash, hashlib.sha256(content).hexdigest())
		self.assertIsNotNone(root.find("ds:Signature", NS))
		policy = root.find(".//{http://uri.etsi.org/01903/v1.3.2#}SigPolicyHash", NS)
		self.assertIsNotNone(policy)
		# criterio 2: importes iguales a los de la factura
		self.assertEqual(root.findtext(".//InvoiceTotals/InvoiceTotal"), f"{si.grand_total:.2f}")
		self.assertEqual(root.findtext(".//InvoiceTotals/TotalTaxOutputs"), "210.00")
		self.assertEqual(len(root.findall(".//AdministrativeCentre")), 3)
		self.assertEqual(
			root.findtext(".//PaymentDetails/Installment/AccountToBeCredited/IBAN"),
			"ES9121000418450200051332",
		)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si.name, "es_einvoice_status"), "Generada")
		# criterio 8: el certificado no se expone, solo su sujeto
		self.assertNotIn(b"PRIVATE KEY", content)

	def test_withholding_and_totals(self):
		si = self.invoice("IVA 21 % con retención 15 %")
		_doc, content, root = self.xml_of(api.generate_facturae(si.name))
		facturae.validate_xml(content)
		self.assertEqual(root.findtext(".//InvoiceTotals/TotalTaxesWithheld"), "150.00")
		self.assertEqual(root.findtext(".//InvoiceTotals/InvoiceTotal"), "1060.00")
		self.assertEqual(root.findtext(".//TaxesWithheld/Tax/TaxTypeCode"), "04")
		self.assertEqual(root.findtext(".//TaxesWithheld/Tax/TaxRate"), "15.00")

	def test_corrective_invoice(self):
		"""Criterio 4: la rectificativa lleva su propia factura electrónica con la referencia."""
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		original = self.invoice()
		credit = make_return_doc("Sales Invoice", original.name)
		credit.es_rectification_reason_code = "16"
		credit.es_correction_method = "02"
		credit.es_rectification_reason = "Devolución de la mitad del servicio"
		credit.items[0].qty = -1
		credit.insert()
		credit.submit()
		_doc, content, root = self.xml_of(api.generate_facturae(credit.name))
		facturae.validate_xml(content)
		self.assertEqual(root.findtext(".//InvoiceHeader/InvoiceClass"), "OR")
		self.assertEqual(root.findtext(".//Corrective/InvoiceNumber"), original.name)
		self.assertEqual(root.findtext(".//Corrective/ReasonCode"), "16")
		self.assertTrue(root.findtext(".//InvoiceTotals/InvoiceTotal").startswith("-"))

	def test_register_in_face_and_block_cancel(self):
		si = self.invoice()
		name = api.generate_facturae(si.name)
		api.register_in_face(name, "REGAGE26e00001234567")
		doc = frappe.get_doc("ES E-Invoice", name)
		self.assertEqual(doc.status, "Registrada en FACe")
		self.assertEqual([h.status for h in doc.history], ["Generada", "Registrada en FACe"])
		with self.assertRaises(frappe.ValidationError):
			api.register_in_face(name, "OTRO")
		with self.assertRaises(frappe.ValidationError):
			api.generate_facturae(si.name)
		si.reload()
		with self.assertRaises(frappe.ValidationError):
			si.cancel()

	def test_regenerate_before_upload_supersedes(self):
		si = self.invoice()
		first = api.generate_facturae(si.name)
		second = api.generate_facturae(si.name)
		self.assertNotEqual(first, second)
		self.assertEqual(frappe.db.get_value("ES E-Invoice", first, "status"), "Anulada")
		self.assertEqual(frappe.db.get_value("Sales Invoice", si.name, "es_einvoice"), second)

	def test_requires_public_administration(self):
		if not frappe.db.exists("Customer", PERSON):
			frappe.get_doc({"doctype": "Customer", "customer_name": PERSON, "tax_id": "12345678Z"}).insert()
			make_address(PERSON, "Customer", PERSON)
		si = self.invoice(customer=PERSON)
		with self.assertRaisesRegex(frappe.ValidationError, "Administración Pública"):
			api.generate_facturae(si.name)

	def test_individual_needs_surnames(self):
		frappe.db.set_value("Customer", CUSTOMER, {"es_person_type": "Física", "es_individual_name": None})
		try:
			si = self.invoice()
			with self.assertRaisesRegex(frappe.ValidationError, "apellido"):
				api.generate_facturae(si.name)
		finally:
			frappe.db.set_value("Customer", CUSTOMER, "es_person_type", None)

	def test_country_codes(self):
		self.assertEqual(codes.alpha3("ES"), "ESP")
		self.assertEqual(codes.alpha3("FR"), "FRA")
		self.assertEqual(codes.alpha3("DE"), "DEU")
		self.assertEqual(codes.province_for("15705"), "A Coruña")

	def test_signature_verifies(self):
		"""La firma XAdES es íntegra: se verifica con el certificado de la credencial."""
		from signxml.xades import XAdESVerifier

		from erpnext_spain.aeat.doctype.es_aeat_credential.es_aeat_credential import pem_paths

		si = self.invoice()
		_doc, content, _root = self.xml_of(api.generate_facturae(si.name))
		cert_path, _key = pem_paths(COMPANY, "SII")
		with open(cert_path, "rb") as f:
			cert = f.read()
		results = XAdESVerifier().verify(content, x509_cert=cert, expect_references=3)
		self.assertTrue(results)
