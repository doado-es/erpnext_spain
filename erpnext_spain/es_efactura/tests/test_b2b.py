# Factura electrónica B2B: UBL, canal, recepción y estados (spec 10, criterios 3-8).

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate
from lxml import etree

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company
from erpnext_spain.es_efactura import b2b, ubl
from erpnext_spain.es_impuestos import initial_data
from erpnext_spain.es_impuestos.tests.test_initial_data import apply_template, ensure_item

NIF_COMPANY = "B12345674"
NIF_CUSTOMER = "A58818501"


class TestB2B(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Factura B2B", "_TEFB")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		frappe.db.set_value(
			"Company",
			cls.company,
			{"tax_id": NIF_COMPANY, "es_einvoice_b2b": 1, "es_einvoice_channel": "Simulado"},
		)
		frappe.clear_document_cache("Company", cls.company)
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.item = ensure_item("_Test ES Servicio B2B")
		for doctype, name, tax_id in (
			("Customer", "_Test ES Cliente B2B", NIF_CUSTOMER),
			("Supplier", "_Test ES Proveedor B2B", NIF_COMPANY),
		):
			if not frappe.db.exists(doctype, name):
				field = "customer_name" if doctype == "Customer" else "supplier_name"
				frappe.get_doc({"doctype": doctype, field: name, "tax_id": tax_id}).insert()

	def tearDown(self):
		frappe.flags.es_einvoice_outbox = frappe.flags.es_einvoice_inbox = frappe.flags.es_einvoice_states = (
			None
		)

	def sale(self, template="IVA 21 %"):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": "_Test ES Cliente B2B",
				"debit_to": pgc.account_by_number(self.company, "4300"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item,
						"qty": 2,
						"rate": 500,
						"income_account": pgc.account_by_number(self.company, "7050"),
						"cost_center": self.cost_center,
					}
				],
				"taxes_and_charges": initial_data.template_name(
					self.company, "Sales Taxes and Charges Template", template
				),
			}
		)
		apply_template(si)
		si.insert()
		si.submit()
		return si

	def e_invoice(self, **filters):
		return frappe.get_last_doc("ES E-Invoice", filters=filters)

	def content(self, doc) -> bytes:
		data = frappe.get_doc("File", {"file_url": doc.file}).get_content()
		return data if isinstance(data, bytes) else data.encode()

	def test_issue_and_send(self):
		"""Criterio 3: UBL válido (XSD UBL 2.1 y reglas EN 16931) y envío por el canal."""
		si = self.sale(template="IVA 21 % con retención 15 %")
		doc = self.e_invoice(sales_invoice=si.name)
		self.assertEqual((doc.direction, doc.scope, doc.format), ("Emitida", "B2B", "UBL 2.1"))
		self.assertEqual(doc.status, "Enviada")
		self.assertEqual(doc.external_id, f"SIM-{doc.name}")
		root = etree.fromstring(self.content(doc))
		self.assertEqual(root.findtext("cac:TaxTotal/cbc:TaxAmount", namespaces=ubl.NS), "210.00")
		self.assertEqual(
			root.findtext("cac:LegalMonetaryTotal/cbc:PayableAmount", namespaces=ubl.NS), "1060.00"
		)
		self.assertEqual(root.findtext("cac:WithholdingTaxTotal/cbc:TaxAmount", namespaces=ubl.NS), "150.00")
		self.assertEqual(ubl.business_rules(root), [])

	def test_credit_note_references_original(self):
		"""Criterio 4."""
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		si = self.sale()
		credit = make_sales_return(si.name)
		credit.es_invoice_type = "R1"
		credit.es_rectification_reason = "Devolución"
		credit.insert()
		credit.submit()
		root = etree.fromstring(self.content(self.e_invoice(sales_invoice=credit.name)))
		self.assertEqual(etree.QName(root).localname, "CreditNote")
		self.assertEqual(
			root.findtext("cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID", namespaces=ubl.NS),
			si.name,
		)
		self.assertEqual(root.findtext("cac:TaxTotal/cbc:TaxAmount", namespaces=ubl.NS), "210.00")

	def test_reception(self):
		"""Criterio 5: proveedor conocido → borrador de compra; NIF desconocido → pendiente."""
		si = self.sale()
		content = self.content(self.e_invoice(sales_invoice=si.name))
		received = frappe.get_doc("ES E-Invoice", b2b.receive_invoice(self.company, content))
		self.assertEqual(received.supplier, "_Test ES Proveedor B2B")
		pi = frappe.get_doc("Purchase Invoice", received.purchase_invoice)
		self.assertEqual((pi.docstatus, pi.bill_no, pi.supplier), (0, si.name, "_Test ES Proveedor B2B"))
		self.assertAlmostEqual(pi.net_total, 1000)

		unknown = content.replace(NIF_COMPANY.encode(), b"B87654321")
		pending = frappe.get_doc("ES E-Invoice", b2b.receive_invoice(self.company, unknown))
		self.assertEqual(pending.status, "Pendiente de proveedor")
		self.assertFalse(pending.purchase_invoice)

	def test_payment_communication(self):
		"""Criterio 6: el pago completo se comunica con su fecha; cancelarlo antes lo retira."""
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		si = self.sale()
		received = frappe.get_doc(
			"ES E-Invoice",
			b2b.receive_invoice(self.company, self.content(self.e_invoice(sales_invoice=si.name))),
		)
		pi = frappe.get_doc("Purchase Invoice", received.purchase_invoice)
		pi.credit_to = pgc.account_by_number(self.company, "4000")
		pi.cost_center = self.cost_center
		pi.save()
		pi.submit()
		payment = get_payment_entry(
			"Purchase Invoice", pi.name, bank_account=pgc.account_by_number(self.company, "5720")
		)
		payment.reference_no, payment.reference_date = "P1", nowdate()
		payment.insert()
		payment.submit()
		received.reload()
		self.assertEqual(
			(received.payment_communication, str(received.payment_date)),
			("Pendiente", str(payment.posting_date)),
		)
		payment.reload()
		self.assertEqual(payment.docstatus, 1)
		payment.cancel()
		received.reload()
		self.assertFalse(received.payment_communication)

		payment = get_payment_entry(
			"Purchase Invoice", pi.name, bank_account=pgc.account_by_number(self.company, "5720")
		)
		payment.reference_no, payment.reference_date = "P2", nowdate()
		payment.insert()
		payment.submit()
		b2b.communicate_payments()
		received.reload()
		self.assertEqual((received.payment_communication, received.status), ("Comunicada", "Pagada"))
		self.assertIn(
			(received.name, "Pagada", str(payment.posting_date), None), frappe.flags.es_einvoice_states
		)

	def test_accept_reject_requires_role(self):
		"""Criterio 7."""
		si = self.sale()
		received = b2b.receive_invoice(self.company, self.content(self.e_invoice(sales_invoice=si.name)))
		with self.assertRaisesRegex(frappe.ValidationError, "motivo"):
			b2b.accept_or_reject(received, accept=False)
		self.assertEqual(
			b2b.accept_or_reject(received, accept=False, reason="Precio incorrecto"), "Rechazada"
		)
		user = "es-einvoice-test@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Factura"}).insert()
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				b2b.accept_or_reject(received)
		finally:
			frappe.set_user("Administrator")

	def test_non_b2b_customer_skipped(self):
		frappe.db.set_value("Company", self.company, "es_einvoice_b2b", 0)
		frappe.clear_document_cache("Company", self.company)
		try:
			si = self.sale()
			self.assertFalse(frappe.db.exists("ES E-Invoice", {"sales_invoice": si.name}))
		finally:
			frappe.db.set_value("Company", self.company, "es_einvoice_b2b", 1)
			frappe.clear_document_cache("Company", self.company)
