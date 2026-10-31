# Facturación masiva, envío por correo y comprobación de NIF/VIES (spec 15, criterios 1-7).

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, nowdate

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company
from erpnext_spain.es_facturacion import bulk, mailing
from erpnext_spain.nif import vies


class TestBulk(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Masivo", "_TEMA")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.warehouse = frappe.db.get_value(
			"Warehouse",
			{
				"company": cls.company,
				"is_group": 0,
				"warehouse_type": ["!=", "Transit"],
				"name": ["like", "Stores%"],
			},
			"name",
		)
		cls.item = "_Test ES Artículo masivo"
		if not frappe.db.exists("Item", cls.item):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": cls.item,
					"item_group": "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 1,
				}
			).insert()
		for doctype, name in (
			("Customer", "_Test ES Cliente masivo 1"),
			("Customer", "_Test ES Cliente masivo 2"),
			("Supplier", "_Test ES Proveedor masivo 1"),
			("Supplier", "_Test ES Proveedor masivo 2"),
		):
			if not frappe.db.exists(doctype, name):
				field = "customer_name" if doctype == "Customer" else "supplier_name"
				frappe.get_doc({"doctype": doctype, field: name}).insert()

	def receipt(self, supplier: str, qty: float = 10, rate: float = 10, posting_date=None):
		doc = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"company": self.company,
				"supplier": supplier,
				"posting_date": posting_date or nowdate(),
				"posting_time": "00:00:01",
				"set_posting_time": 1,
				"items": [
					{
						"item_code": self.item,
						"qty": qty,
						"rate": rate,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		).insert()
		doc.submit()
		return doc

	def delivery(self, customer: str, posting_date=None, qty: float = 1):
		self.receipt("_Test ES Proveedor masivo 1", qty=qty, posting_date=posting_date)
		doc = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"company": self.company,
				"customer": customer,
				"posting_date": posting_date or nowdate(),
				"posting_time": "23:00:00",
				"set_posting_time": 1,
				"items": [
					{
						"item_code": self.item,
						"qty": qty,
						"rate": 100,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		).insert()
		doc.submit()
		return doc

	def test_grouped_by_customer(self):
		"""Criterio 1: tres albaranes de dos clientes → dos facturas enlazadas."""
		a = self.delivery("_Test ES Cliente masivo 1")
		b = self.delivery("_Test ES Cliente masivo 1")
		c = self.delivery("_Test ES Cliente masivo 2")
		result = bulk.invoice_delivery_notes([a.name, b.name, c.name], submit=True)
		self.assertEqual(len(result["invoices"]), 2)
		invoice = frappe.get_doc(
			"Sales Invoice",
			next(
				i
				for i in result["invoices"]
				if frappe.db.get_value("Sales Invoice", i, "customer") == "_Test ES Cliente masivo 1"
			),
		)
		self.assertEqual(sorted({row.delivery_note for row in invoice.items}), sorted([a.name, b.name]))
		self.assertEqual(frappe.db.get_value("Delivery Note", a.name, "per_billed"), 100)

	def test_grouped_by_month(self):
		"""Criterio 2."""
		earlier = self.delivery("_Test ES Cliente masivo 2", posting_date=add_months(nowdate(), -1))
		later = self.delivery("_Test ES Cliente masivo 2")
		result = bulk.invoice_delivery_notes([earlier.name, later.name], group_by_period=True)
		self.assertEqual(len(result["invoices"]), 2)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", result["invoices"][0], "docstatus"), 0
		)  # borrador por defecto

	def test_billed_skipped(self):
		"""Criterio 3."""
		note = self.delivery("_Test ES Cliente masivo 1")
		bulk.invoice_delivery_notes([note.name], submit=True)
		result = bulk.invoice_delivery_notes([note.name])
		self.assertEqual(result["invoices"], [])
		self.assertEqual(result["skipped"][0]["reason"], "ya está facturado")

	def test_purchase_receipts(self):
		"""Criterio 4."""
		first = self.receipt("_Test ES Proveedor masivo 1")
		second = self.receipt("_Test ES Proveedor masivo 1")
		other = self.receipt("_Test ES Proveedor masivo 2")
		with self.assertRaisesRegex(frappe.ValidationError, "mismo proveedor"):
			bulk.invoice_purchase_receipts([first.name, other.name], "F-1", nowdate())
		name = bulk.invoice_purchase_receipts([first.name, second.name], "F-2026-77", nowdate())
		invoice = frappe.get_doc("Purchase Invoice", name)
		self.assertEqual(
			(invoice.bill_no, str(invoice.bill_date), invoice.supplier),
			("F-2026-77", nowdate(), "_Test ES Proveedor masivo 1"),
		)
		self.assertEqual(
			sorted({row.purchase_receipt for row in invoice.items}), sorted([first.name, second.name])
		)

	def test_mailing(self):
		"""Criterio 5: un correo por factura con PDF, registro y sin reenvío."""
		if not frappe.db.exists("Email Account", {"default_outgoing": 1}):
			frappe.get_doc(
				{
					"doctype": "Email Account",
					"email_account_name": "_Test ES Facturas",
					"email_id": "facturas@example.com",
					"enable_outgoing": 1,
					"default_outgoing": 1,
					"smtp_server": "localhost",
					"no_smtp_authentication": 1,
				}
			).insert()
		note = self.delivery("_Test ES Cliente masivo 1")
		invoice = bulk.invoice_delivery_notes([note.name], submit=True)["invoices"][0]
		frappe.db.set_value("Sales Invoice", invoice, "contact_email", "cliente@example.com")
		without = self.delivery("_Test ES Cliente masivo 2")
		other = bulk.invoice_delivery_notes([without.name], submit=True)["invoices"][0]
		counts = mailing.run([invoice, other])
		self.assertEqual((counts["sent"], counts["errors"]), (1, 1))
		queue = frappe.get_last_doc("Email Queue", filters={"reference_name": invoice})
		self.assertIn("cliente@example.com", [r.recipient for r in queue.recipients])
		attachments = frappe.parse_json(queue.attachments)
		self.assertEqual(
			(attachments[0]["name"], attachments[0]["print_format"]), (invoice, "Factura España VeriFactu")
		)
		self.assertTrue(frappe.db.get_value("Sales Invoice", invoice, "es_emailed_on"))
		self.assertEqual(frappe.db.get_value(mailing.LOG, {"sales_invoice": other}, "status"), "Error")
		again = mailing.run([invoice])
		self.assertEqual((again["sent"], again["skipped"]), (0, 1))
		self.assertEqual(mailing.run([invoice], resend=1)["sent"], 1)

	def test_requires_role(self):
		"""Criterio 7."""
		user = "es-bulk-test@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Masivo"}).insert()
		frappe.set_user(user)
		try:
			for call in (
				lambda: bulk.invoice_delivery_notes(["X"]),
				lambda: bulk.invoice_purchase_receipts(["X"], "1", nowdate()),
				lambda: mailing.send_invoices(["X"]),
				lambda: vies.check_parties("Customer", ["X"]),
			):
				with self.assertRaises(frappe.PermissionError):
					call()
		finally:
			frappe.set_user("Administrator")


class TestVies(IntegrationTestCase):
	def party(self, name: str, tax_id: str) -> str:
		if not frappe.db.exists("Customer", name):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": name,
					"tax_id": tax_id,
					"country": "France" if tax_id.startswith(("FR", "DE")) else None,
				}
			).insert()
		return name

	def test_vies_and_spanish(self):
		"""Criterio 6."""
		valid = self.party("_Test ES VIES válido", "FR40303265045")
		invalid = self.party("_Test ES VIES no válido", "DE123456789")
		spanish = self.party("_Test ES VIES español", "12345678Z")
		frappe.flags.es_vies_responses = {
			"FR40303265045": {"valid": True, "name": "SA ODIGEO"},
			"DE123456789": {"valid": False, "name": ""},
		}
		try:
			result = vies.check_parties("Customer", [valid, invalid, spanish])
		finally:
			frappe.flags.es_vies_responses = None
		self.assertEqual(result, {valid: vies.VALID, invalid: vies.INVALID, spanish: vies.SPANISH_OK})
		self.assertEqual(frappe.db.get_value("Customer", valid, "es_vies_name"), "SA ODIGEO")
		self.assertTrue(frappe.db.get_value("Customer", valid, "es_vies_checked_on"))

	def test_service_unavailable(self):
		name = self.party("_Test ES VIES caído", "FR40303265045")
		frappe.flags.es_vies_responses = {}
		try:
			self.assertEqual(vies.check_party("Customer", name), vies.UNAVAILABLE)
		finally:
			frappe.flags.es_vies_responses = None
