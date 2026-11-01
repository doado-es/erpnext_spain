# Modelos 115, 180, 190, 349, 347 y 390: cálculo y fichero de la AEAT.

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, nowdate

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_iva.tests.test_vat_rows import VatTestCase
from erpnext_spain.es_modelos import model_115, model_180, model_190, model_347, model_349, model_390, returns
from erpnext_spain.es_modelos.tests.test_returns import current_period
from erpnext_spain.es_retenciones import codes
from erpnext_spain.es_sepa.tests.test_sepa import ensure_address

CONTACT = {"contact_name": "Ana Pérez", "contact_phone": "981000000"}


def file_content(doc) -> str:
	content = frappe.get_doc("File", {"file_url": doc.aeat_file}).get_content()
	return content.decode("latin-1") if isinstance(content, bytes) else content


def records(doc) -> list[str]:
	return [line for line in file_content(doc).split("\r\n") if line]


def tax_return(company: str, model: str, period: str, **extra):
	year = getdate(nowdate()).year
	for name, docstatus in frappe.get_all(
		"ES Tax Return",
		filters={"company": company, "tax_model": model, "fiscal_year": year, "period": period},
		fields=["name", "docstatus"],
		as_list=True,
	):
		if docstatus == 1:
			frappe.get_doc("ES Tax Return", name).cancel()
		frappe.delete_doc("ES Tax Return", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "ES Tax Return",
			"company": company,
			"tax_model": model,
			"fiscal_year": year,
			"period": period,
			**extra,
		}
	)


class TestWithholdingModels(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		from erpnext_spain.es_retenciones.tests.test_withholding import TestWithholdingsMade

		super().setUpClass()
		TestWithholdingsMade.setUpClass()
		cls.case = TestWithholdingsMade("test_professional_15")
		cls.company = cls.case.company

	@classmethod
	def tearDownClass(cls):
		from erpnext_spain.es_retenciones.tests.test_withholding import TestWithholdingsMade

		TestWithholdingsMade.tearDownClass()
		super().tearDownClass()

	def rental(self):
		supplier = self.case.supplier("_Test ES Arrendador modelos", category=codes.LEASING)
		ensure_address("Supplier", supplier)
		prop = frappe.get_doc(
			{
				"doctype": "ES Leased Property",
				"title": "Local modelos",
				"company": self.company,
				"lessor": supplier,
				"situation": codes.PROPERTY_SITUATIONS[0],
				"cadastral_reference": "9872023VH5797S0001WX",
				"address": "Calle Mayor 1",
				"municipality": "Madrid",
				"postal_code": "28001",
			}
		).insert()
		pi = self.case.purchase_invoice(supplier).insert()
		pi.es_leased_property = prop.name
		pi.save()
		pi.submit()
		return supplier, prop

	def test_115_and_180(self):
		year, period = current_period()
		before = model_115.compute(frappe._dict(company=self.company, fiscal_year=year, period=period))[0]
		supplier, prop = self.rental()
		after = model_115.compute(frappe._dict(company=self.company, fiscal_year=year, period=period))[0]
		self.assertAlmostEqual(after["02"] - before["02"], 1000)
		self.assertAlmostEqual(after["03"] - before["03"], 190)

		doc = tax_return(self.company, "115", period, declaration_type="I - Ingreso")
		doc.insert()
		self.assertAlmostEqual(doc.result, returns.box(doc, "03"))
		doc.submit()
		content = file_content(doc)
		self.assertTrue(content.startswith(f"<T1150{year}{period}0000><AUX>"))
		page1 = content[content.index("<T11501000>") : content.index("</T11501000>") + 12]
		self.assertEqual(len(page1), 500)
		self.assertEqual(int(page1[140:157]), round(returns.box(doc, "03") * 100))
		self.assertEqual(int(page1[174:191]), round(doc.result * 100))

		annual = tax_return(self.company, "180", "0A", **CONTACT)
		annual.insert()
		line = next(row for row in annual.lines if row.party == supplier)
		self.assertEqual((line.property, line.province_code), (prop.name, "28"))
		self.assertAlmostEqual(line.withheld, 190)
		self.assertAlmostEqual(line.rate, 19)
		annual.submit()
		header, *perceptors = records(annual)
		self.assertTrue(all(len(r) == 500 for r in [header, *perceptors]))
		self.assertEqual(header[:8], f"1180{year}")
		self.assertEqual(int(header[135:144]), len(annual.lines))
		mine = next(r for r in perceptors if r[17:26] == model_180.inf.nif(line.tax_id))
		self.assertEqual(mine[78], " ")
		self.assertEqual(int(mine[79:92]), 100000)
		self.assertEqual(mine[92:96], "1900")
		self.assertEqual(int(mine[96:109]), 19000)
		self.assertEqual(mine[113], "1")
		self.assertEqual(mine[114:134], "9872023VH5797S0001WX")
		self.assertEqual(mine[322:327], "28001")

	def test_180_needs_spanish_property(self):
		_supplier, prop = self.rental()
		frappe.db.set_value("ES Leased Property", prop.name, "situation", codes.PROPERTY_SITUATIONS[4])
		frappe.clear_document_cache("ES Leased Property", prop.name)
		annual = tax_return(self.company, "180", "0A", **CONTACT)
		annual.insert()
		self.assertRaisesRegex(frappe.ValidationError, "extranjero", annual.submit)

	def test_190(self):
		supplier = self.case.supplier("_Test ES Profesional 190")
		ensure_address("Supplier", supplier)
		self.case.purchase_invoice(supplier).insert().submit()
		doc = tax_return(self.company, "190", "0A", contact_email="ana@example.com", **CONTACT)
		doc.insert()
		line = next(row for row in doc.lines if row.party == supplier)
		self.assertEqual((line.operation_key, line.subkey), ("G", "01"))
		self.assertAlmostEqual((line.amount, line.withheld), (1000, 150))
		doc.submit()
		header, *perceptors = records(doc)
		self.assertTrue(all(len(r) == 500 for r in [header, *perceptors]))
		self.assertEqual(header[175:225].strip(), "ANA@EXAMPLE.COM")
		mine = next(r for r in perceptors if r[17:26] == model_190.inf.nif(line.tax_id))
		self.assertEqual((mine[75:77], mine[77], mine[78:80]), ("28", "G", "01"))
		self.assertEqual(int(mine[81:94]), 100000)
		self.assertEqual(int(mine[94:107]), 15000)

	def test_informative_needs_contact(self):
		doc = tax_return(self.company, "190", "0A")
		doc.insert()
		self.assertRaisesRegex(frappe.ValidationError, "contacto", doc.submit)

	def test_period_must_match_model(self):
		self.assertRaisesRegex(
			frappe.ValidationError, "no admite", tax_return(self.company, "190", "1T").insert
		)


class TestVatModels(VatTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.eu_customer = eu_party("Customer", "_Test ES Cliente UE modelos", "FR40303265045")
		cls.eu_supplier = eu_party("Supplier", "_Test ES Proveedor UE modelos", "DE129273398")
		cls.es_customer = frappe.db.get_value("Customer", {"customer_name": "_Test ES Cliente 347"})
		if not cls.es_customer:
			cls.es_customer = (
				frappe.get_doc(
					{"doctype": "Customer", "customer_name": "_Test ES Cliente 347", "tax_id": "B12345674"}
				)
				.insert()
				.name
			)
		ensure_address("Customer", cls.es_customer)

	def purchase_from(self, supplier: str, template: str, rate: float = 1000):
		original = self.supplier
		self.supplier = supplier
		try:
			return self.purchase(template, rate)
		finally:
			self.supplier = original

	def test_349_operators_and_rectification(self):
		_year, period = current_period()
		sale = self.sale(customer=self.eu_customer, template="Entrega intracomunitaria")
		self.purchase_from(self.eu_supplier, "Adquisición intracomunitaria de bienes 21 %", 400)
		self.purchase_from(self.eu_supplier, "Adquisición intracomunitaria de servicios 21 %", 300)
		doc = tax_return(self.company, "349", period, **CONTACT)
		doc.insert()
		keys = {(row.party, row.operation_key): flt(row.amount) for row in doc.lines}
		self.assertGreaterEqual(keys[(self.eu_customer, "E")], 1000)
		self.assertGreaterEqual(keys[(self.eu_supplier, "A")], 400)
		self.assertGreaterEqual(keys[(self.eu_supplier, "I")], 300)
		doc.submit()
		header, *operators = records(doc)
		self.assertTrue(all(len(r) == 500 for r in [header, *operators]))
		self.assertEqual(header[135:137], period)
		self.assertEqual(int(header[137:146]), len(doc.lines))
		mine = next(r for r in operators if r[75:92].strip() == "FR40303265045" and r[132] == "E")
		self.assertEqual(int(mine[133:146]), round(keys[(self.eu_customer, "E")] * 100))
		self.assertEqual(sale.docstatus, 1)

	def test_349_keys(self):
		row = frappe._dict
		self.assertEqual(model_349.operation_key(row(book="Expedidas", vat_classification="E5")), "E")
		self.assertEqual(
			model_349.operation_key(row(book="Expedidas", vat_classification="N2", id_type="02")), "S"
		)
		self.assertIsNone(
			model_349.operation_key(row(book="Expedidas", vat_classification="N2", id_type="06"))
		)
		self.assertEqual(
			model_349.operation_key(
				row(
					book="Recibidas", self_assessed=1, operation_type="Adquisición intracomunitaria de bienes"
				)
			),
			"A",
		)

	def test_347_threshold_quarters_and_exclusions(self):
		_year, quarter = current_period()
		self.sale(customer=self.es_customer, lines=((None, 3000),))
		self.sale(customer=self.eu_customer, template="Entrega intracomunitaria", lines=((None, 9000),))
		doc = tax_return(self.company, "347", "0A", **CONTACT)
		doc.insert()
		line = next(row for row in doc.lines if row.party == self.es_customer)
		self.assertEqual(line.operation_key, "B")
		self.assertGreaterEqual(line.amount, 3630)
		self.assertAlmostEqual(line.get(f"amount_q{quarter[0]}"), line.amount)
		self.assertFalse([row for row in doc.lines if row.party == self.eu_customer])  # va en el 349
		doc.submit()
		header, *declared = records(doc)
		self.assertTrue(all(len(r) == 500 for r in [header, *declared]))
		mine = next(r for r in declared if r[17:26] == "B12345674")
		self.assertEqual((mine[75], mine[76:78], mine[81]), ("D", "28", "B"))
		self.assertEqual(int(mine[83:96] + mine[96:98]), round(line.amount * 100))

	def test_347_and_390_not_for_sii(self):
		frappe.db.set_value("Company", self.company, "es_sii_enabled", 1)
		frappe.clear_document_cache("Company", self.company)
		try:
			for model in ("347", "390"):
				with self.subTest(model=model):
					self.assertRaisesRegex(
						frappe.ValidationError, "SII", tax_return(self.company, model, "0A", **CONTACT).insert
					)
		finally:
			frappe.db.set_value("Company", self.company, "es_sii_enabled", 0)
			frappe.clear_document_cache("Company", self.company)

	def test_390_boxes_and_pages(self):
		year = getdate(nowdate()).year
		probe = frappe._dict(company=self.company, fiscal_year=year)
		before = model_390.compute(probe)[0]
		self.sale(lines=((None, 1000), (self.reduced_item, 500)))
		self.purchase("IVA soportado 21 %", rate=400)
		self.purchase("IVA soportado 21 % bien de inversión", rate=100)
		after = model_390.compute(probe)[0]
		delta = {b: round(after.get(b, 0) - before.get(b, 0), 2) for b in set(after) | set(before)}
		self.assertEqual((delta["05"], delta["06"]), (1000, 210))
		self.assertEqual((delta["03"], delta["04"]), (500, 50))
		self.assertEqual((delta["605"], delta["606"], delta["48"], delta["49"]), (400, 84, 400, 84))
		self.assertEqual((delta["613"], delta["614"], delta["50"], delta["51"]), (100, 21, 100, 21))
		self.assertEqual(delta["99"], 1500)

		doc = tax_return(self.company, "390", "0A", previous_compensation=10)
		doc.insert()
		self.assertAlmostEqual(returns.box(doc, "65"), returns.box(doc, "47") - returns.box(doc, "64"))
		self.assertAlmostEqual(doc.result, returns.box(doc, "65") - 10)
		doc.submit()
		content = file_content(doc)
		self.assertTrue(content.startswith(f"<T3900{year}0A0000><AUX>"))
		self.assertTrue(content.endswith(f"</T3900{year}0A0000>"))
		layout = model_390.layout()
		for page_id in model_390.PAGES:
			with self.subTest(page=page_id):
				start = content.index(f"<T390{page_id}>")
				end = content.index(f"</T390{page_id}>") + len(f"</T390{page_id}>")
				self.assertEqual(end - start, layout[page_id]["length"])
		page2 = content[content.index("<T39002000>") :]
		self.assertEqual(int(page2[216:233]), round(returns.box(doc, "05") * 100))  # [05] en la posición 217
		page6 = content[content.index("<T39006000>") :]
		self.assertEqual(page6[114:119], "10000")  # [87] territorio común 100,00 %


def eu_party(doctype: str, name: str, tax_id: str) -> str:
	field = "customer_name" if doctype == "Customer" else "supplier_name"
	existing = frappe.db.get_value(doctype, {field: name})
	if existing:
		return existing
	country = {"FR": "France", "DE": "Germany"}[tax_id[:2]]
	return (
		frappe.get_doc({"doctype": doctype, field: name, "tax_id": tax_id, "country": country}).insert().name
	)
