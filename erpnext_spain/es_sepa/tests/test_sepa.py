# SEPA: transferencias, adeudos, respuestas y devoluciones (spec 11, criterios 1-8).

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowdate
from lxml import etree

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company
from erpnext_spain.es_impuestos.tests.test_initial_data import ensure_item
from erpnext_spain.es_sepa import credit_transfer, direct_debit, status, xml
from erpnext_spain.es_sepa import payment_order as payment_order_effects
from erpnext_spain.es_sepa.utils import creditor_identifier

NS001 = {"p": f"urn:iso:std:iso:20022:tech:xsd:{xml.PAIN_001}"}
NS008 = {"p": f"urn:iso:std:iso:20022:tech:xsd:{xml.PAIN_008}"}


def make_iban(account: str) -> str:
	"""IBAN español válido a partir de entidad + oficina + 10 dígitos de cuenta
	(se ignoran los dígitos de control de la cadena y se recalculan)."""
	from stdnum.es import ccc

	entity_office, number = account[:8], account[-10:]
	digits = ccc.calc_check_digits(f"{entity_office}00{number}")
	return ccc.to_iban(f"{entity_office}{digits}{number}")


def ensure_address(link_doctype: str, link_name: str, city: str | None = "Madrid") -> str:
	title = f"{link_name} SEPA"
	name = frappe.db.get_value("Address", {"address_title": title})
	if name:
		return name
	address = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": title,
			"address_type": "Billing",
			"address_line1": "Calle Mayor 1",
			"city": city or "-",
			"pincode": "28001",
			"country": "Spain",
			"is_primary_address": 1,
			"links": [{"link_doctype": link_doctype, "link_name": link_name}],
		}
	).insert()
	if not city:
		frappe.db.set_value("Address", address.name, "city", "")
	return address.name


def two_term_template() -> str:
	"""Condiciones de pago con dos plazos del 50 % a 30 y 60 días."""
	name = "_Test ES Dos plazos"
	if frappe.db.exists("Payment Terms Template", name):
		return name
	terms = []
	for days in (30, 60):
		term = f"_Test ES 50 % a {days} días"
		if not frappe.db.exists("Payment Term", term):
			frappe.get_doc(
				{
					"doctype": "Payment Term",
					"payment_term_name": term,
					"invoice_portion": 50,
					"due_date_based_on": "Day(s) after invoice date",
					"credit_days": days,
				}
			).insert()
		terms.append(
			{
				"payment_term": term,
				"invoice_portion": 50,
				"due_date_based_on": "Day(s) after invoice date",
				"credit_days": days,
			}
		)
	frappe.get_doc({"doctype": "Payment Terms Template", "template_name": name, "terms": terms}).insert()
	return name


class SepaTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES SEPA", "_TESE")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		frappe.db.set_value("Company", cls.company, {"tax_id": "B12345674", "es_sepa_submit_payments": 1})
		frappe.clear_document_cache("Company", cls.company)
		ensure_address("Company", cls.company)
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.bank = "_Test ES Banco SEPA"
		if not frappe.db.exists("Bank", cls.bank):
			frappe.get_doc({"doctype": "Bank", "bank_name": cls.bank, "swift_number": "CAIXESBBXXX"}).insert()
		cls.company_account = cls.bank_account(
			"Cuenta SEPA",
			make_iban("21000418450200051332"),
			company_account=pgc.account_by_number(cls.company, "5720"),
		)
		cls.ensure_norms(cls.company_account, {"Transferencias SEPA": "000", "Adeudos SEPA": "001"})
		cls.item = ensure_item("_Test ES Servicio SEPA")

	@classmethod
	def bank_ledger(cls, number: str, name: str) -> str:
		"""Subcuenta 572x propia: ERPNext admite una sola Bank Account por cuenta contable."""
		ledger = frappe.db.get_value("Account", {"company": cls.company, "account_number": number}, "name")
		if ledger:
			return ledger
		return (
			frappe.get_doc(
				{
					"doctype": "Account",
					"company": cls.company,
					"account_name": name,
					"account_number": number,
					"parent_account": frappe.db.get_value(
						"Account", {"company": cls.company, "account_number": "572"}
					),
					"account_type": "Bank",
				}
			)
			.insert()
			.name
		)

	@classmethod
	def ensure_norms(cls, bank_account: str, norms: dict[str, str], **extra) -> None:
		"""Normas bancarias de una cuenta de la compañía (sufijo y datos de confirming)."""
		doc = frappe.get_doc("Bank Account", bank_account)
		present = {row.norm for row in doc.es_norms}
		for norm, suffix in norms.items():
			if norm not in present:
				doc.append(
					"es_norms", {"norm": norm, "suffix": suffix, **(extra if norm == "Confirming" else {})}
				)
		for row in doc.es_norms:
			if row.norm in norms:
				row.suffix = norms[row.norm]
			if row.norm == "Confirming":
				row.update(extra)
		doc.save()

	@classmethod
	def bank_account(cls, name: str, iban: str, party_type=None, party=None, company_account=None) -> str:
		existing = frappe.db.get_value("Bank Account", {"account_name": name, "bank": cls.bank}, "name")
		if existing:
			return existing
		doc = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": name,
				"bank": cls.bank,
				"iban": iban,
				"is_company_account": 1 if company_account else 0,
				"company": cls.company,
				"account": company_account,
				"party_type": party_type,
				"party": party,
			}
		)
		return doc.insert().name

	@classmethod
	def party(cls, doctype: str, name: str, account_number: str, address: bool = True) -> tuple[str, str]:
		if not frappe.db.exists(doctype, name):
			field = "supplier_name" if doctype == "Supplier" else "customer_name"
			frappe.get_doc({"doctype": doctype, field: name}).insert()
		if address:
			ensure_address(doctype, name)
		account = cls.bank_account(f"{name} cuenta", make_iban(account_number), doctype, name)
		return name, account


class TestCreditTransfer(SepaTestCase):
	def purchase(self, supplier: str, rate: float, payment_terms_template: str | None = None):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": supplier,
				"bill_no": frappe.generate_hash(length=6),
				**({"payment_terms_template": payment_terms_template} if payment_terms_template else {}),
				"credit_to": pgc.account_by_number(self.company, "4000"),
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"rate": rate,
						"expense_account": pgc.account_by_number(self.company, "6000"),
						"cost_center": self.cost_center,
					}
				],
			}
		).insert()
		pi.submit()
		return pi

	def payment_order(self, invoices: list) -> str:
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		order = frappe.get_doc(
			{
				"doctype": "Payment Order",
				"company": self.company,
				"payment_order_type": "Payment Entry",
				"company_bank_account": self.company_account,
				"posting_date": nowdate(),
				"es_sepa_execution_date": add_days(nowdate(), 1),
				"references": [],
			}
		)
		for pi, bank_account in invoices:
			payment = get_payment_entry(
				"Purchase Invoice", pi.name, bank_account=pgc.account_by_number(self.company, "5720")
			)
			payment.reference_no = pi.name
			payment.reference_date = nowdate()
			payment.insert()
			order.append(
				"references",
				{
					"reference_doctype": "Payment Entry",
					"reference_name": payment.name,
					"amount": payment.paid_amount,
					"supplier": pi.supplier,
					"bank_account": bank_account,
				},
			)
		order.insert()
		order.submit()
		return order.name

	def test_three_invoices_two_suppliers(self):
		"""Criterios 1 y 7: pain.001.001.09 válido; EndToEndId en el fichero y en el pago."""
		first, first_account = self.party("Supplier", "_Test ES Proveedor SEPA 1", "21000418450200051341")
		second, second_account = self.party("Supplier", "_Test ES Proveedor SEPA 2", "21000418450200051350")
		order = self.payment_order(
			[
				(self.purchase(first, 100), first_account),
				(self.purchase(first, 200), first_account),
				(self.purchase(second, 300), second_account),
			]
		)
		url = credit_transfer.generate_credit_transfer(order)
		content = frappe.get_doc("File", {"file_url": url}).get_content()
		root = etree.fromstring(content if isinstance(content, bytes) else content.encode())
		self.assertTrue(xml.schema(xml.PAIN_001).validate(root))
		self.assertEqual(root.findtext(".//p:GrpHdr/p:NbOfTxs", namespaces=NS001), "3")
		self.assertEqual(root.findtext(".//p:GrpHdr/p:CtrlSum", namespaces=NS001), "600.00")
		ids = [e.text for e in root.iterfind(".//p:CdtTrfTxInf/p:PmtId/p:EndToEndId", namespaces=NS001)]
		doc = frappe.get_doc("Payment Order", order)
		self.assertEqual(ids, [row.es_end_to_end_id for row in doc.references])
		self.assertEqual(
			frappe.db.get_value("Payment Entry", doc.references[0].reference_name, "es_end_to_end_id"), ids[0]
		)
		self.assertEqual(
			root.findtext(".//p:InitgPty/p:Id/p:OrgId/p:Othr/p:Id", namespaces=NS001), "B12345674000"
		)

	def add_effects(self, rows, payment_order=None) -> str:
		return payment_order_effects.add_effects(
			[{k: r[k] for k in ("purchase_invoice", "supplier", "payment_term", "amount")} for r in rows],
			payment_order=payment_order,
			company=self.company,
			company_bank_account=self.company_account,
			posting_date=nowdate(),
			execution_date=add_days(nowdate(), 2),
		)

	def test_payment_order_by_effects(self):
		"""Efectos por vencimiento: pago en borrador por proveedor, validado con la orden."""
		supplier, account = self.party("Supplier", "_Test ES Proveedor Efectos", "21000418450200051705")
		pi = self.purchase(supplier, 200, payment_terms_template=two_term_template())
		found = payment_order_effects.get_effects(self.company, suppliers=[supplier])
		self.assertEqual(
			[(r["purchase_invoice"], r["amount"], r["bank_account"]) for r in found],
			[(pi.name, 100, account)] * 2,
		)

		order = self.add_effects(found)
		payment = frappe.get_doc("Payment Entry", {"payment_order": order})
		self.assertEqual(payment.docstatus, 0)
		self.assertEqual(
			sorted(r.payment_term for r in payment.references), sorted(r["payment_term"] for r in found)
		)
		# Los efectos en un pago en borrador no se ofrecen a otra orden.
		self.assertEqual(payment_order_effects.get_effects(self.company, suppliers=[supplier]), [])

		# Quitar el pago de la orden lo borra y deja los efectos libres.
		doc = frappe.get_doc("Payment Order", order)
		doc.references = []
		doc.append("references", self.other_reference())
		doc.save()
		self.assertFalse(frappe.db.exists("Payment Entry", payment.name))
		found = payment_order_effects.get_effects(self.company, suppliers=[supplier])
		self.assertEqual(len(found), 2)

		self.add_effects(found[:1], payment_order=order)
		doc = frappe.get_doc("Payment Order", order)
		doc.submit()
		payment = frappe.get_doc("Payment Entry", {"payment_order": order})
		self.assertEqual(payment.docstatus, 1)
		self.assertEqual(str(payment.posting_date), add_days(nowdate(), 2))
		self.assertAlmostEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 100)
		self.assertAlmostEqual(
			frappe.db.get_value(
				"Payment Schedule",
				{"parent": pi.name, "payment_term": found[0]["payment_term"]},
				"outstanding",
			),
			0,
		)
		url = credit_transfer.generate_credit_transfer(order)
		content = frappe.get_doc("File", {"file_url": url}).get_content()
		root = etree.fromstring(content if isinstance(content, bytes) else content.encode())
		self.assertTrue(xml.schema(xml.PAIN_001).validate(root))

	def other_reference(self) -> dict:
		"""Fila de otra orden para que la tabla (obligatoria) no quede vacía."""
		supplier, account = self.party("Supplier", "_Test ES Proveedor Efectos Otro", "21000418450200051714")
		pi = self.purchase(supplier, 10)
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		payment = get_payment_entry(
			"Purchase Invoice", pi.name, bank_account=pgc.account_by_number(self.company, "5720")
		)
		payment.reference_no = pi.name
		payment.reference_date = nowdate()
		payment.insert()
		return {
			"reference_doctype": "Payment Entry",
			"reference_name": payment.name,
			"amount": payment.paid_amount,
			"supplier": supplier,
			"bank_account": account,
		}

	def test_payment_order_effects_rules(self):
		supplier, _account = self.party(
			"Supplier", "_Test ES Proveedor Efectos Reglas", "21000418450200051723"
		)
		pi = self.purchase(supplier, 100)
		[effect] = payment_order_effects.get_effects(self.company, suppliers=[supplier])
		with self.assertRaisesRegex(frappe.ValidationError, "ya no está pendiente"):
			self.add_effects([{**effect, "amount": 150}])
		# Vencimientos de confirming o domiciliados van en sus propias remesas.
		frappe.db.set_value("Payment Schedule", {"parent": pi.name}, "mode_of_payment", "Confirming")
		self.assertEqual(payment_order_effects.get_effects(self.company, suppliers=[supplier]), [])

	def test_payment_order_effects_need_supplier_account(self):
		supplier, account = self.party("Supplier", "_Test ES Proveedor Sin IBAN", "21000418450200051732")
		frappe.db.set_value("Bank Account", account, "disabled", 1)
		self.purchase(supplier, 100)
		found = payment_order_effects.get_effects(self.company, suppliers=[supplier])
		self.assertIsNone(found[0]["bank_account"])
		with self.assertRaisesRegex(frappe.ValidationError, "_Test ES Proveedor Sin IBAN"):
			self.add_effects(found)

	def test_deleting_draft_order_deletes_its_payments(self):
		supplier, _account = self.party(
			"Supplier", "_Test ES Proveedor Efectos Borrar", "21000418450200051741"
		)
		self.purchase(supplier, 100)
		order = self.add_effects(payment_order_effects.get_effects(self.company, suppliers=[supplier]))
		payment = frappe.db.get_value("Payment Entry", {"payment_order": order})
		frappe.delete_doc("Payment Order", order)
		self.assertFalse(frappe.db.exists("Payment Entry", payment))

	def test_unstructured_address_blocks(self):
		"""Criterio 3."""
		supplier, account = self.party(
			"Supplier", "_Test ES Proveedor sin dirección", "21000418450200051369", address=False
		)
		order = self.payment_order([(self.purchase(supplier, 50), account)])
		with self.assertRaisesRegex(frappe.ValidationError, "_Test ES Proveedor sin dirección"):
			credit_transfer.generate_credit_transfer(order)

	def test_requires_role(self):
		"""Criterio 8."""
		user = "es-sepa-test@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "SEPA"}).insert()
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				credit_transfer.generate_credit_transfer("PMO-X")
		finally:
			frappe.set_user("Administrator")


class TestDirectDebit(SepaTestCase):
	def mandate(self, customer: str, account: str, scheme: str = "CORE", status_value: str = "Activo") -> str:
		"""Mandato SEPA en la cuenta bancaria del cliente; devuelve la cuenta."""
		doc = frappe.get_doc("Bank Account", account)
		doc.update(
			{
				"es_sepa_scheme": scheme,
				"es_sepa_mandate_status": status_value,
				"es_sepa_mandate_type": "Recurrente",
				"es_sepa_mandate_reference": doc.es_sepa_mandate_reference
				or f"MND-{frappe.generate_hash(length=10).upper()}",
				"es_sepa_mandate_date": add_days(nowdate(), -30),
				"es_sepa_first_debit_done": 0,
			}
		)
		doc.save()
		return account

	def sale(self, customer: str, rate: float = 121, payment_terms_template: str | None = None):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": customer,
				"debit_to": pgc.account_by_number(self.company, "4300"),
				"cost_center": self.cost_center,
				**(
					{"payment_terms_template": payment_terms_template}
					if payment_terms_template
					else {"due_date": nowdate()}
				),
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"rate": rate,
						"income_account": pgc.account_by_number(self.company, "7050"),
						"cost_center": self.cost_center,
					}
				],
			}
		).insert()
		si.submit()
		return si

	def batch(self, lines: list[tuple]) -> frappe.model.document.Document:
		return frappe.get_doc(
			{
				"doctype": "ES Sepa Direct Debit Batch",
				"company": self.company,
				"bank_account": self.company_account,
				"scheme": "CORE",
				"collection_date": add_days(nowdate(), 3),
				"lines": [
					{"sales_invoice": si.name, "bank_account": mandate, "amount": si.outstanding_amount}
					for si, mandate in lines
				],
			}
		)

	def test_core_batch(self):
		"""Criterios 2 y 7: pain.008.001.08 con identificador de acreedor y mandato."""
		customer, account = self.party("Customer", "_Test ES Cliente SEPA 1", "21000418450200051378")
		mandate = self.mandate(customer, account)
		si = self.sale(customer)
		batch = self.batch([(si, mandate)]).insert()
		batch.submit()
		batch.reload()
		content = frappe.get_doc("File", {"file_url": batch.sepa_file}).get_content()
		root = etree.fromstring(content if isinstance(content, bytes) else content.encode())
		self.assertTrue(xml.schema(xml.PAIN_008).validate(root))
		self.assertEqual(
			root.findtext(".//p:CdtrSchmeId/p:Id/p:PrvtId/p:Othr/p:Id", namespaces=NS008),
			creditor_identifier("B12345674", "001"),  # sufijo de la norma de adeudos, no el de transferencias
		)
		self.assertEqual(
			root.findtext(".//p:GrpHdr/p:InitgPty/p:Id/p:OrgId/p:Othr/p:Id", namespaces=NS008), "B12345674001"
		)
		self.assertEqual(
			root.findtext(".//p:MndtRltdInf/p:MndtId", namespaces=NS008),
			frappe.db.get_value("Bank Account", mandate, "es_sepa_mandate_reference"),
		)
		line = batch.lines[0]
		self.assertEqual(
			root.findtext(".//p:DrctDbtTxInf/p:PmtId/p:EndToEndId", namespaces=NS008), line.end_to_end_id
		)
		self.assertEqual(
			frappe.db.get_value("Payment Entry", line.payment_entry, "es_end_to_end_id"), line.end_to_end_id
		)
		self.assertAlmostEqual(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount"), 0)
		self.assertEqual(
			str(frappe.db.get_value("Bank Account", mandate, "es_sepa_last_debit")),
			str(batch.collection_date),
		)

	def test_effects_per_installment(self):
		"""Un efecto por vencimiento; el cobro de una remesa se aplica a su plazo."""
		customer, account = self.party("Customer", "_Test ES Cliente Efectos", "21000418450200051500")
		mandate = self.mandate(customer, account)
		si = self.sale(customer, 121, payment_terms_template=two_term_template())
		found = direct_debit.get_effects(self.company, customers=[customer])
		self.assertEqual(
			[(e["sales_invoice"], e["amount"]) for e in found], [(si.name, 60.5), (si.name, 60.5)]
		)
		first, second = found
		self.assertEqual(first["bank_account"], mandate)
		self.assertLess(str(first["due_date"]), str(second["due_date"]))

		batch = frappe.get_doc(
			{
				"doctype": "ES Sepa Direct Debit Batch",
				"company": self.company,
				"bank_account": self.company_account,
				"scheme": "CORE",
				"collection_date": add_days(nowdate(), 3),
				"lines": [first],
			}
		).insert()
		# Mientras la remesa está en borrador, su efecto no se ofrece a otras.
		remaining = direct_debit.get_effects(self.company, customers=[customer])
		self.assertEqual([e["payment_term"] for e in remaining], [second["payment_term"]])
		self.assertEqual(
			len(direct_debit.get_effects(self.company, customers=[customer], batch=batch.name)), 2
		)

		batch.submit()
		payment = frappe.get_doc("Payment Entry", batch.lines[0].payment_entry)
		self.assertEqual(
			[(r.reference_name, r.payment_term, r.allocated_amount) for r in payment.references],
			[(si.name, first["payment_term"], 60.5)],
		)
		self.assertAlmostEqual(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount"), 60.5)
		self.assertAlmostEqual(
			frappe.db.get_value(
				"Payment Schedule", {"parent": si.name, "payment_term": first["payment_term"]}, "outstanding"
			),
			0,
		)
		after = direct_debit.get_effects(self.company, customers=[customer])
		self.assertEqual([(e["payment_term"], e["amount"]) for e in after], [(second["payment_term"], 60.5)])

	def test_effect_repeated_or_over_outstanding(self):
		customer, account = self.party("Customer", "_Test ES Cliente Efectos 2", "21000418450200051519")
		mandate = self.mandate(customer, account)
		si = self.sale(customer, 121, payment_terms_template=two_term_template())
		first, second = direct_debit.get_effects(self.company, customers=[customer])
		batch = frappe.get_doc(
			{
				"doctype": "ES Sepa Direct Debit Batch",
				"company": self.company,
				"bank_account": self.company_account,
				"scheme": "CORE",
				"collection_date": add_days(nowdate(), 3),
				"lines": [first, first],
			}
		)
		self.assertRaisesRegex(frappe.ValidationError, "repetido", batch.insert)
		batch.lines = []
		batch.append(
			"lines",
			{
				"sales_invoice": si.name,
				"bank_account": mandate,
				"amount": 100,
				"payment_term": first["payment_term"],
			},
		)
		batch.append(
			"lines",
			{
				"sales_invoice": si.name,
				"bank_account": mandate,
				"amount": 30,
				"payment_term": second["payment_term"],
			},
		)
		self.assertRaisesRegex(frappe.ValidationError, "pendiente", batch.insert)

	def test_invalid_mandates_rejected(self):
		"""Criterio 4: mandato cancelado o de otro esquema."""
		customer, account = self.party("Customer", "_Test ES Cliente SEPA 2", "21000418450200051387")
		si = self.sale(customer)
		for status_value, scheme in (("Cancelado", "CORE"), ("Activo", "B2B")):
			mandate = self.mandate(customer, account, scheme=scheme, status_value=status_value)
			with (
				self.subTest(mandate=mandate),
				self.assertRaisesRegex(frappe.ValidationError, "Mandato no válido|mandato"),
			):
				self.batch([(si, mandate)]).insert()

	def status_report(self, end_to_end_id: str) -> str:
		content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:{xml.PAIN_002}"><CstmrPmtStsRpt>
<GrpHdr><MsgId>R1</MsgId><CreDtTm>2026-10-31T10:00:00</CreDtTm></GrpHdr>
<OrgnlGrpInfAndSts><OrgnlMsgId>X</OrgnlMsgId><OrgnlMsgNmId>pain.008.001.08</OrgnlMsgNmId><GrpSts>PART</GrpSts></OrgnlGrpInfAndSts>
<OrgnlPmtInfAndSts><OrgnlPmtInfId>X-1</OrgnlPmtInfId><TxInfAndSts><OrgnlEndToEndId>{end_to_end_id}</OrgnlEndToEndId>
<TxSts>RJCT</TxSts><StsRsnInf><Rsn><Cd>AC04</Cd></Rsn></StsRsnInf></TxInfAndSts></OrgnlPmtInfAndSts>
</CstmrPmtStsRpt></Document>""".encode()
		return (
			frappe.get_doc(
				{"doctype": "File", "file_name": "pain002.xml", "content": content, "is_private": 1}
			)
			.insert()
			.file_url
		)

	def test_rejection_reopens_invoice(self):
		"""Criterios 5 y 7: la operación rechazada se marca y la factura vuelve a estar pendiente."""
		customer, account = self.party("Customer", "_Test ES Cliente SEPA 3", "21000418450200051396")
		mandate = self.mandate(customer, account)
		si = self.sale(customer)
		batch = self.batch([(si, mandate)]).insert()
		batch.submit()
		batch.reload()
		result = status.import_direct_debit_status(
			batch.name, self.status_report(batch.lines[0].end_to_end_id)
		)
		self.assertEqual(result["rejected"], 1)
		batch.reload()
		self.assertEqual(batch.lines[0].status, "Rechazada")
		self.assertEqual(batch.lines[0].reason_code, "AC04")
		self.assertAlmostEqual(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount"), 121)

	def test_return_with_charges(self):
		"""Criterio 6: la devolución reabre la factura y anota los gastos."""
		customer, account = self.party("Customer", "_Test ES Cliente SEPA 4", "21000418450200051405")
		mandate = self.mandate(customer, account)
		si = self.sale(customer)
		batch = self.batch([(si, mandate)]).insert()
		batch.submit()
		batch.reload()
		result = status.register_return(batch.name, batch.lines[0].name, "MD06", 3.5)
		self.assertAlmostEqual(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount"), 121)
		charges = frappe.get_doc("Journal Entry", result["charges_entry"])
		self.assertAlmostEqual(flt(charges.total_debit), 3.5)
		batch.reload()
		self.assertEqual(batch.lines[0].status, "Devuelta")


class TestBankAccountSepaData(SepaTestCase):
	def test_missing_norm_blocks(self):
		"""Una cuenta sin la norma pedida no genera fichero: error con el remedio."""
		from erpnext_spain.es_sepa.bank_account import CONFIRMING, norm

		self.assertEqual(norm(self.company_account, "Adeudos SEPA").suffix, "001")
		bare = self.bank_account(
			"Cuenta sin normas",
			make_iban("21000418450200051603"),
			company_account=self.bank_ledger("5723", "Banco sin normas"),
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Normas bancarias"):
			norm(bare, CONFIRMING)

	def test_mandate_reference_unique_and_customer_only(self):
		first_customer, first = self.party("Customer", "_Test ES Cliente mandato 1", "21000418450200051500")
		_second_customer, second = self.party(
			"Customer", "_Test ES Cliente mandato 2", "21000418450200051519"
		)
		TestDirectDebit.mandate(self, first_customer, first)
		reference = frappe.db.get_value("Bank Account", first, "es_sepa_mandate_reference")
		doc = frappe.get_doc("Bank Account", second)
		doc.update(
			{
				"es_sepa_scheme": "CORE",
				"es_sepa_mandate_reference": reference,
				"es_sepa_mandate_date": nowdate(),
			}
		)
		with self.assertRaisesRegex(frappe.ValidationError, "única"):
			doc.save()
		company = frappe.get_doc("Bank Account", self.company_account)
		company.es_sepa_scheme = "CORE"
		with self.assertRaisesRegex(frappe.ValidationError, "clientes"):
			company.save()
