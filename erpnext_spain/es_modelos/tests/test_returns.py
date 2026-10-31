# Modelos 303 y 111: cálculo, corrección manual y fichero AEAT (spec 07).

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, nowdate

from erpnext_spain.es_iva.tests.test_vat_register import VatTestCase
from erpnext_spain.es_modelos import returns


def current_period():
	date = getdate(nowdate())
	return date.year, f"{(date.month - 1) // 3 + 1}T"


class TestModel303(VatTestCase):
	def tax_return(self, **extra):
		year, period = current_period()
		name = frappe.db.get_value(
			"ES Tax Return",
			{
				"company": self.company,
				"tax_model": "303",
				"fiscal_year": year,
				"period": period,
				"docstatus": 0,
			},
		)
		if name:
			frappe.delete_doc("ES Tax Return", name)
		return frappe.get_doc(
			{
				"doctype": "ES Tax Return",
				"company": self.company,
				"tax_model": "303",
				"fiscal_year": year,
				"period": period,
				**extra,
			}
		)

	def test_boxes_from_register(self):
		year, period = current_period()
		before = returns.compute_303(self.company, year, period)
		self.sale(lines=((None, 1000), (self.reduced_item, 500)))
		self.purchase("IVA soportado 21 %", rate=400)
		self.purchase("Inversión del sujeto pasivo 21 % (compras)", rate=200)
		after = returns.compute_303(self.company, year, period)
		delta = {box: round(after.get(box, 0) - before.get(box, 0), 2) for box in set(after) | set(before)}
		self.assertEqual((delta["07"], delta["09"]), (1000, 210))
		self.assertEqual((delta["04"], delta["06"]), (500, 50))
		self.assertEqual((delta["12"], delta["13"]), (200, 42))  # ISP autorrepercutida
		self.assertEqual((delta["28"], delta["29"]), (600, 126))  # 400 + 200 de ISP deducible
		self.assertEqual(delta["27"], 302)
		self.assertEqual(delta["46"], 302 - 126)

	def test_manual_correction_and_file(self):
		doc = self.tax_return(previous_compensation=50, applied_compensation=20)
		doc.insert()
		box = next(row for row in doc.boxes if row.box == "09")
		box.amount += 10
		box.manual = 1
		doc.save()
		self.assertAlmostEqual(returns.box(doc, "27"), returns.box(doc, "27"))
		expected = returns.box(doc, "27") - returns.box(doc, "45") - 20
		self.assertAlmostEqual(doc.result, round(expected, 2))
		returns.calculate(doc)
		self.assertEqual(next(row for row in doc.boxes if row.box == "09").manual, 1)  # se conserva

		doc.submit()
		content = frappe.get_doc("File", {"file_url": doc.aeat_file}).get_content()
		content = content.decode("latin-1") if isinstance(content, bytes) else content
		year, period = current_period()
		self.assertTrue(content.startswith(f"<T3030{year}{period}0000><AUX>"))
		self.assertTrue(content.endswith(f"</T3030{year}{period}0000>"))
		page1 = content[content.index("<T30301000>") : content.index("</T30301000>") + 12]
		self.assertEqual(len(page1), 1581)
		self.assertEqual(page1[342:347], "02100")  # tipo del 21 % en la posición 343
		self.assertEqual(int(page1[347:364]), round(returns.box(doc, "09") * 100))
		page3 = content[content.index("<T30303000>") : content.index("</T30303000>") + 12]
		self.assertEqual(len(page3), 1017)
		self.assertEqual(returns.signed(-12.5, 17), "N0000000000001250")


class TestModel111(IntegrationTestCase):
	def test_professional_withholdings(self):
		from erpnext_spain.es_retenciones.tests.test_withholding import TestWithholdingsMade

		case = TestWithholdingsMade("test_professional_15")
		TestWithholdingsMade.setUpClass()
		try:
			year, period = current_period()
			before = returns.compute_111(case.company, year, period)
			supplier = case.supplier("_Test ES Profesional 111")
			pi = case.purchase_invoice(supplier).insert()
			pi.submit()
			after = returns.compute_111(case.company, year, period)
			self.assertAlmostEqual(after["08"] - before.get("08", 0), 1000)
			self.assertAlmostEqual(after["09"] - before.get("09", 0), 150)
			self.assertGreaterEqual(after["07"], 1)
			doc = frappe.get_doc(
				{
					"doctype": "ES Tax Return",
					"company": case.company,
					"tax_model": "111",
					"fiscal_year": year,
					"period": period,
				}
			)
			doc.insert()
			self.assertAlmostEqual(doc.result, after["28"])
			doc.submit()
			content = frappe.get_doc("File", {"file_url": doc.aeat_file}).get_content()
			content = content.decode("latin-1") if isinstance(content, bytes) else content
			page1 = content[content.index("<T11101000>") : content.index("</T11101000>") + 12]
			self.assertEqual(len(page1), 1000)
			self.assertEqual(int(page1[217:234]), round(after["09"] * 100))
		finally:
			TestWithholdingsMade.tearDownClass()
