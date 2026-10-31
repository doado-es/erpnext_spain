# SII: registros, plazos, envío, bajas y cuadre (spec 14, criterios 1, 2, 4-8).

import json
import unittest.mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

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

	def configure(self, **values):
		"""Ajustes SII de la compañía para un test (se restauran al terminar)."""
		previous = frappe.db.get_value("Company", self.company, list(values), as_dict=True)
		frappe.db.set_value("Company", self.company, values)
		frappe.clear_document_cache("Company", self.company)

		def restore():
			frappe.db.set_value("Company", self.company, previous)
			frappe.clear_document_cache("Company", self.company)

		self.addCleanup(restore)

	def test_period_limits_generation(self):
		"""Facturas con fecha de registro fuera de [inicio, fin] no generan registro."""
		self.configure(es_sii_activation_date=add_days(nowdate(), 1), es_sii_end_date=None)
		self.assertFalse(frappe.db.exists("ES Sii Record", {"voucher_no": self.sale().name}))
		self.configure(es_sii_activation_date=None, es_sii_end_date=add_days(nowdate(), -1))
		self.assertFalse(frappe.db.exists("ES Sii Record", {"voucher_no": self.sale().name}))
		self.configure(es_sii_activation_date=add_days(nowdate(), -1), es_sii_end_date=nowdate())
		self.assertTrue(frappe.db.exists("ES Sii Record", {"voucher_no": self.sale().name}))

	def test_wait_days_and_legal_deadline(self):
		"""Altas: N días hábiles desde el registro contable, sin pasar del plazo legal."""
		self.configure(es_sii_wait_days=2)
		record = self.record(self.sale())
		self.assertEqual(getdate(record.send_on), outbox.add_working_days(nowdate(), 2))
		self.configure(es_sii_wait_days=10)
		record = self.record(self.sale())
		self.assertEqual(getdate(record.send_on), getdate(record.deadline))

	def test_automatic_waits_and_changes_go_at_once(self):
		self.configure(es_sii_wait_days=2)
		waiting = self.sale()
		client = FakeSiiClient()
		self.drain(client)
		self.assertEqual(self.record(waiting).status, outbox.PENDING)
		self.assertFalse(client.payloads)

		# Baja de una factura ya registrada: sin esperar.
		self.configure(es_sii_wait_days=0)
		sent = self.sale()
		self.drain(client)
		self.assertEqual(self.record(sent).status, outbox.OK)
		self.configure(es_sii_wait_days=2)
		sent.cancel()
		cancellation = self.record(sent, communication="Baja")
		self.assertEqual(getdate(cancellation.send_on), getdate(nowdate()))
		self.drain(client)
		self.assertEqual(frappe.db.get_value("ES Sii Record", cancellation.name, "status"), outbox.OK)

	def test_recompute_when_wait_days_change(self):
		self.configure(es_sii_wait_days=3)
		record = self.record(self.sale())
		company = frappe.get_doc("Company", self.company)
		company.es_sii_wait_days = 1
		company.save()
		self.assertEqual(
			getdate(frappe.db.get_value("ES Sii Record", record.name, "send_on")),
			outbox.add_working_days(nowdate(), 1),
		)

	def test_manual_strategy_and_list_action(self):
		"""Manual: el trabajo programado no envía; la acción de la lista sí."""
		self.configure(es_sii_strategy="Manual")
		sale, purchase = self.sale(), self.purchase("IVA soportado 21 %")
		client = FakeSiiClient()
		self.drain(client)
		self.assertEqual(self.record(sale).status, outbox.PENDING)
		with unittest.mock.patch.object(outbox.SiiDriver, "get_client", return_value=client):
			result = outbox.send_invoices("Sales Invoice", [sale.name])
			self.assertEqual(result, {self.record(sale).name: outbox.OK})
			outbox.send_invoices("Purchase Invoice", [purchase.name])
		self.assertEqual(self.record(purchase).status, outbox.OK)
		with self.assertRaises(frappe.ValidationError):
			outbox.send_invoices("Sales Invoice", [sale.name])  # ya no hay pendientes

	def test_notifications_by_channel(self):
		self.configure(es_sii_notify_email=1, es_sii_notify_desktop=1)
		self.sale()
		with (
			unittest.mock.patch("frappe.sendmail") as sendmail,
			unittest.mock.patch("frappe.publish_realtime") as realtime,
		):
			self.drain(FakeSiiClient())
		sendmail.assert_called()
		self.assertIn("registros enviados", sendmail.call_args.kwargs["subject"])
		self.assertTrue([c for c in realtime.call_args_list if c.args[0] == "erpnext_spain_notice"])
		self.assertTrue(
			frappe.db.exists(
				"Notification Log",
				{"document_name": self.company, "subject": ["like", "%registros enviados%"]},
			)
		)

		self.configure(es_sii_notify_email=0, es_sii_notify_desktop=0)
		self.sale()
		with (
			unittest.mock.patch("frappe.sendmail") as sendmail,
			unittest.mock.patch("frappe.publish_realtime") as realtime,
		):
			self.drain(FakeSiiClient())
		sendmail.assert_not_called()
		self.assertFalse([c for c in realtime.call_args_list if c.args[0] == "erpnext_spain_notice"])

	def test_endpoints_from_settings(self):
		self.assertEqual(
			outbox.endpoint(records.ISSUED, "pruebas"),
			"https://www7.aeat.es/wlpl/SSII-FACT/ws/fe/SiiFactFEV1SOAP",
		)
		settings = frappe.get_single("ES Settings")
		previous = settings.sii_received_url_production
		settings.sii_received_url_production = "https://example.test/sii/fr"
		settings.save()
		self.addCleanup(frappe.db.set_single_value, "ES Settings", "sii_received_url_production", previous)
		frappe.clear_document_cache("ES Settings", "ES Settings")
		self.assertEqual(outbox.endpoint(records.RECEIVED, "produccion"), "https://example.test/sii/fr")

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

	def test_history_in_fiscal_tab(self):
		"""Pestaña de la factura: el registro del SII llega con el documento (onload)."""
		from erpnext_spain.es_facturacion.fiscal_tab import ONLOAD_KEY

		for doc in (self.sale(), self.purchase("IVA soportado 21 %")):
			with self.subTest(doctype=doc.doctype):
				loaded = frappe.get_doc(doc.doctype, doc.name)
				loaded.run_method("onload")
				data = loaded.get_onload().get(ONLOAD_KEY)
				self.assertEqual(data["system"], "SII")
				self.assertEqual([row.name for row in data["sii"]], [self.record(doc).name])
				self.assertEqual(data["verifactu"], [])

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
