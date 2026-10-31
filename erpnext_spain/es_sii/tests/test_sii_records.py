# SII: registros, plazos, envío, bajas y cuadre (spec 14, criterios 1, 2, 4-8).

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, nowdate

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company
from erpnext_spain.es_impuestos import initial_data
from erpnext_spain.es_impuestos.tests.test_initial_data import apply_template, ensure_item
from erpnext_spain.es_sii import outbox, records


class FakeSiiClient:
	"""Responde como la AEAT: estado por registro y CSV."""

	def __init__(self, states: dict | None = None):
		self.states = states or {}
		self.payloads = []

	def send(self, payload):
		self.payloads.append(payload)
		lines = []
		for record in next(v for k, v in payload["datos"].items() if k.startswith("Registro")):
			number = record["IDFactura"]["NumSerieFacturaEmisor"]
			state, code = self.states.get(number, ("Correcto", None))
			lines.append(
				{
					"IDFactura": record["IDFactura"],
					"EstadoRegistro": state,
					"CodigoErrorRegistro": code,
					"DescripcionErrorRegistro": "NIF no identificado" if code else None,
				}
			)
		return {"EstadoEnvio": "ParcialmenteCorrecto", "CSV": "CSV1234567890", "RespuestaLinea": lines}


class TestSii(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES SII Libros", "_TESL")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		frappe.db.set_value(
			"Company", cls.company, {"tax_id": "B12345674", "es_sii_enabled": 1, "es_verifactu_enabled": 0}
		)
		frappe.clear_document_cache("Company", cls.company)
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.item = ensure_item("_Test ES Servicio SII")
		for doctype, name, tax_id in (
			("Customer", "_Test ES Cliente SII", "12345678Z"),
			("Supplier", "_Test ES Proveedor SII", "B58834813"),
			("Supplier", "_Test ES Proveedor SII UE", "FR40303265045"),
		):
			if not frappe.db.exists(doctype, name):
				field = "customer_name" if doctype == "Customer" else "supplier_name"
				country = {"country": "France"} if tax_id.startswith("FR") else {}
				frappe.get_doc({"doctype": doctype, field: name, "tax_id": tax_id, **country}).insert()
		from erpnext_spain.erpnext_spain.initial_data import ensure_holiday_list

		ensure_holiday_list()

	def sale(self, template="IVA 21 %", **extra):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": "_Test ES Cliente SII",
				"debit_to": pgc.account_by_number(self.company, "4300"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"rate": 1000,
						"income_account": pgc.account_by_number(self.company, "7050"),
						"cost_center": self.cost_center,
					}
				],
				"taxes_and_charges": initial_data.template_name(
					self.company, "Sales Taxes and Charges Template", template
				),
				**extra,
			}
		)
		apply_template(si)
		si.insert()
		si.submit()
		return si

	def purchase(self, template: str, supplier="_Test ES Proveedor SII"):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": supplier,
				"bill_no": frappe.generate_hash(length=8).upper(),
				"bill_date": nowdate(),
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
				"taxes_and_charges": initial_data.template_name(
					self.company, "Purchase Taxes and Charges Template", template
				),
			}
		)
		apply_template(pi)
		pi.insert()
		pi.submit()
		return pi

	def record(self, doc, **filters):
		return frappe.get_last_doc("ES Sii Record", filters={"voucher_no": doc.name, **filters})

	def drain(self, client):
		from erpnext_spain.aeat.manager import AEATOutboxManager

		AEATOutboxManager().drain([outbox.SiiDriver(client)])

	def test_working_days(self):
		"""Criterio 1: 4 días hábiles saltando fin de semana y festivo (8/12)."""
		self.assertEqual(outbox.add_working_days("2026-12-04", 4), getdate("2026-12-11"))
		self.assertEqual(outbox.deadline(records.RECEIVED, "2026-12-30"), getdate("2027-01-07"))

	def test_issued_record(self):
		"""Criterios 1 y 2: alta pendiente con fecha límite; el contenido valida contra el XSD."""
		si = self.sale()
		record = self.record(si)
		self.assertEqual((record.book, record.communication, record.status), ("Emitidas", "A0", "Pendiente"))
		self.assertEqual(record.deadline, outbox.deadline(records.ISSUED, si.posting_date))
		content = json.loads(record.content)
		detail = content["FacturaExpedida"]["TipoDesglose"]["DesgloseFactura"]["Sujeta"]["NoExenta"]
		self.assertEqual(detail["TipoNoExenta"], "S1")
		self.assertEqual(
			detail["DesgloseIVA"]["DetalleIVA"][0],
			{"TipoImpositivo": "21.00", "BaseImponible": "1000.00", "CuotaRepercutida": "210.00"},
		)
		self.assertEqual(content["FacturaExpedida"]["Contraparte"]["NIF"], "12345678Z")

	def test_special_cases(self):
		"""Criterio 7: ISP, intracomunitaria y rectificativa con sus claves y desgloses."""
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		isp = json.loads(self.record(self.purchase("Inversión del sujeto pasivo 21 % (compras)")).content)
		self.assertIn("InversionSujetoPasivo", isp["FacturaRecibida"]["DesgloseFactura"])
		self.assertEqual(isp["FacturaRecibida"]["CuotaDeducible"], "210.00")

		intra = json.loads(
			self.record(
				self.purchase("Adquisición intracomunitaria de bienes 21 %", "_Test ES Proveedor SII UE")
			).content
		)
		self.assertEqual(intra["FacturaRecibida"]["ClaveRegimenEspecialOTrascendencia"], "09")
		self.assertEqual(intra["IDFactura"]["IDEmisorFactura"]["IDOtro"]["IDType"], "02")

		si = self.sale()
		credit = make_sales_return(si.name)
		credit.es_invoice_type = "R1"
		credit.es_rectification_reason = "Devolución"
		credit.insert()
		credit.submit()
		rectification = json.loads(self.record(credit).content)["FacturaExpedida"]
		self.assertEqual((rectification["TipoFactura"], rectification["TipoRectificativa"]), ("R1", "I"))

	def test_send_and_errors(self):
		"""Criterios 3 (simulado) y 4: estado por registro y CSV; el rechazo se corrige con un reenvío."""
		good, bad = self.sale(), self.sale()
		client = FakeSiiClient({bad.name: ("Incorrecto", "1104")})
		self.drain(client)
		ok = self.record(good)
		self.assertEqual((ok.status, ok.csv), ("Correcto", "CSV1234567890"))
		self.assertTrue(ok.aeat_response)
		wrong = self.record(bad)
		self.assertEqual((wrong.status, wrong.error_code), ("Incorrecto", "1104"))
		new = outbox.resend(wrong.name)
		self.assertEqual(frappe.db.get_value("ES Sii Record", wrong.name, "status"), "Sustituido")
		self.assertEqual(
			frappe.db.get_value("ES Sii Record", new, ["status", "communication"]), ("Pendiente", "A0")
		)

	def test_cancel_after_sending(self):
		"""Criterio 5: anular una factura enviada genera la baja."""
		si = self.sale()
		self.drain(FakeSiiClient())
		si.reload()
		si.cancel()
		baja = self.record(si, communication="Baja")
		self.assertEqual(baja.status, "Pendiente")
		records.validate_records(self.company, records.ISSUED, records.CANCEL, [json.loads(baja.content)])
		client = FakeSiiClient()
		self.drain(client)
		self.assertEqual(client.payloads[-1]["operacion"], "AnulacionLRFacturasEmitidas")
		self.assertEqual(frappe.db.get_value("ES Sii Record", baja.name, "status"), "Correcto")

	def test_cancel_before_sending_voids(self):
		si = self.sale()
		si.cancel()
		self.assertEqual(self.record(si).status, "Anulado")

	def test_exclusive_with_verifactu(self):
		"""Criterio 6: con SII no hay registros VeriFactu; con los dos forzados, ninguno."""
		si = self.sale()
		self.assertFalse(frappe.db.exists("ES Verifactu Billing Record", {"sales_invoice": si.name}))
		frappe.db.set_value("Company", self.company, "es_verifactu_enabled", 1)
		frappe.clear_document_cache("Company", self.company)
		try:
			from erpnext_spain.utils.gating import is_sii_active

			self.assertFalse(is_sii_active(self.company))
		finally:
			frappe.db.set_value("Company", self.company, "es_verifactu_enabled", 0)
			frappe.clear_document_cache("Company", self.company)

	def test_reconciliation(self):
		"""Criterio 8: el cuadre detecta una factura que no está en la AEAT."""
		first, second = self.sale(), self.sale()
		date = getdate(first.posting_date)
		registered = [{"number": first.name, "total": first.base_grand_total}]
		result = outbox.compare(self.company, records.ISSUED, date.year, date.month, registered)
		self.assertIn(second.name, result["missing_in_aeat"])
		self.assertNotIn(first.name, result["missing_in_aeat"])
		self.assertEqual(result["not_in_books"], [])
