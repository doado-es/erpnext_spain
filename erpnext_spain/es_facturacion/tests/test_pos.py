# Ventas por TPV: tipo de factura por defecto, serie del perfil de TPV y renombrado
# al número fiscal visible para el navegador (localname).

import frappe

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_facturacion import pos
from erpnext_spain.es_facturacion.tests.test_billing import (
	DRAFT_SERIES,
	SERIES_F1,
	SERIES_R1,
	BillingTestCase,
)
from erpnext_spain.es_impuestos.tests.test_initial_data import ensure_party

SERIES_F2 = "FS-.ABBR.-.YY.-.#####"
SERIES_R5 = "RS-.ABBR.-.YY.-.#####"
POS_SERIES = "T1-.ABBR.-.#####"


class TestPos(BillingTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.walk_in = ensure_party("Customer", "_Test ES Cliente mostrador")
		cls.profile = cls.pos_profile("_Test ES TPV 1", POS_SERIES)

	@classmethod
	def pos_profile(cls, name: str, series: str | None = None) -> str:
		if frappe.db.exists("POS Profile", name):
			frappe.db.set_value("POS Profile", name, {"es_series": series, "es_invoice_type": "F2"})
			return name
		warehouse = frappe.db.get_value("Warehouse", {"company": cls.company, "is_group": 0}, "name")
		return (
			frappe.get_doc(
				{
					"doctype": "POS Profile",
					"name": name,
					"company": cls.company,
					"customer": cls.walk_in,
					"currency": "EUR",
					"warehouse": warehouse,
					"write_off_account": pgc.account_by_number(cls.company, "6590"),
					"write_off_cost_center": cls.cost_center,
					"write_off_limit": 1,
					"payments": [{"mode_of_payment": "Cash", "default": 1}],
					"es_invoice_type": "F2",
					"es_series": series,
				}
			)
			.insert()
			.name
		)

	def setUp(self):
		doc = frappe.get_doc("Company", self.company)
		doc.es_fiscal_numbering = 1
		doc.es_draft_series = DRAFT_SERIES
		doc.set("es_invoice_series", [])
		for series, invoice_type in (
			(SERIES_F1, "F1"),
			(SERIES_R1, "R1"),
			(SERIES_F2, "F2"),
			(SERIES_R5, "R5"),
		):
			doc.append("es_invoice_series", {"series": series, "invoice_type": invoice_type})
		doc.save()
		frappe.clear_document_cache("Company", self.company)
		frappe.db.set_value("Customer", self.walk_in, "es_invoice_type", None)
		frappe.clear_document_cache("Customer", self.walk_in)

	def pos_invoice(self, customer=None, **extra):
		si = self.invoice(
			customer=customer or self.walk_in,
			is_pos=1,
			pos_profile=self.profile,
			payments=[{"mode_of_payment": "Cash", "amount": 0}],
			**extra,
		)
		si.insert()
		si.payments[0].amount = si.grand_total
		si.save()
		return si

	def test_pos_sale_is_simplified_with_pos_series(self):
		si = self.pos_invoice()
		self.assertEqual(si.es_invoice_type, "F2")
		draft = si.name
		si.submit()
		self.assertTrue(si.name.startswith(f"T1-{self.abbr}-"), si.name)
		# El navegador (también el TPV) pasa al nombre fiscal con la respuesta del submit.
		self.assertEqual(si.localname, draft)

	def test_customer_type_wins_in_pos(self):
		frappe.db.set_value("Customer", self.walk_in, "es_invoice_type", "F1")
		frappe.clear_document_cache("Customer", self.walk_in)
		si = self.pos_invoice()
		self.assertEqual(si.es_invoice_type, "F1")
		si.submit()
		self.assertTrue(si.name.startswith(f"FN-{self.abbr}-"), si.name)

	def test_simplified_customer_type_only_in_pos(self):
		frappe.db.set_value("Customer", self.walk_in, "es_invoice_type", "F2")
		frappe.clear_document_cache("Customer", self.walk_in)
		si = self.invoice(customer=self.walk_in).insert()
		self.assertEqual(si.es_invoice_type, "F1")

	def test_pos_return_is_r5_with_reason(self):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		si = self.pos_invoice()
		si.submit()
		ret = make_sales_return(si.name)
		if not ret.payments:
			ret.append("payments", {"mode_of_payment": "Cash"})
		ret.payments[0].amount = ret.grand_total
		ret.insert()
		self.assertEqual(ret.es_invoice_type, "R5")
		self.assertEqual(ret.es_rectification_reason, pos.POS_RETURN_REASON)
		ret.submit()
		self.assertTrue(ret.name.startswith(f"RS-{self.abbr}-"), ret.name)

	def test_ordinary_invoice_rename_sets_localname(self):
		si = self.invoice().insert()
		draft = si.name
		si.submit()
		self.assertEqual(si.localname, draft)

	def test_pos_profile_series_rules(self):
		profile = frappe.get_doc("POS Profile", self.profile)
		profile.es_series = "T1"
		self.assertRaisesRegex(frappe.ValidationError, "#", profile.save)
		profile.reload()
		profile.es_series = SERIES_F1
		self.assertRaisesRegex(frappe.ValidationError, "F1", profile.save)
