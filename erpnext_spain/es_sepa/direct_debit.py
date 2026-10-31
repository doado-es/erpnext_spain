# Remesas de adeudos SEPA (spec 11 §5): selección de facturas, validaciones,
# fichero pain.008 y cobros.

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from erpnext_spain.es_sepa import xml
from erpnext_spain.es_sepa.credit_transfer import (
	attach,
	bank_account_party,
	check_role,
	company_address,
	presenter_id,
	sepa_creditor_id,
)
from erpnext_spain.es_sepa.doctype.es_sepa_mandate.es_sepa_mandate import is_expired
from erpnext_spain.es_sepa.utils import check_parties, party_address
from erpnext_spain.utils.gating import is_pgc_company

DIRECT_DEBIT_MODE = "Domiciliación bancaria"


def mandate_for(customer: str, company: str, scheme: str) -> str | None:
	default = frappe.get_cached_value("Customer", customer, "es_sepa_mandate")
	if default and frappe.db.get_value(
		"ES Sepa Mandate", default, ["status", "scheme", "company"], as_dict=True
	) == {"status": "Activo", "scheme": scheme, "company": company}:
		return default
	return frappe.db.get_value(
		"ES Sepa Mandate",
		{"customer": customer, "company": company, "scheme": scheme, "status": "Activo"},
		"name",
	)


@frappe.whitelist()
def get_invoices(
	company: str, scheme: str = "CORE", from_due_date: str | None = None, to_due_date: str | None = None
) -> list[dict]:
	"""Facturas validadas pendientes con modo de pago «Domiciliación bancaria» y
	mandato activo del esquema."""
	frappe.has_permission("Sales Invoice", "read", throw=True)
	filters = {"company": company, "docstatus": 1, "outstanding_amount": [">", 0], "is_return": 0}
	if from_due_date:
		filters["due_date"] = [">=", from_due_date]
	if to_due_date:
		filters.setdefault("due_date", [])
		filters["due_date"] = (
			["between", [from_due_date, to_due_date]] if from_due_date else ["<=", to_due_date]
		)
	rows = []
	for invoice in frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=["name", "customer", "outstanding_amount", "due_date"],
		order_by="due_date, name",
	):
		mode = frappe.db.get_value(
			"Payment Schedule", {"parent": invoice.name, "mode_of_payment": DIRECT_DEBIT_MODE}, "name"
		) or frappe.get_cached_value("Customer", invoice.customer, "es_sepa_mandate")
		if not mode:
			continue
		mandate = mandate_for(invoice.customer, company, scheme)
		if not mandate:
			continue
		rows.append(
			{
				"sales_invoice": invoice.name,
				"customer": invoice.customer,
				"mandate": mandate,
				"amount": invoice.outstanding_amount,
			}
		)
	return rows


def validate_batch(doc) -> None:
	if not is_pgc_company(doc.company):
		frappe.throw(_("La compañía {0} no tiene el plan PGC aplicado.").format(frappe.bold(doc.company)))
	if not frappe.db.get_value("Bank Account", doc.bank_account, "is_company_account"):
		frappe.throw(
			_("La cuenta de abono {0} no es una cuenta de la compañía.").format(frappe.bold(doc.bank_account))
		)
	seen = set()
	for line in doc.lines:
		invoice = frappe.db.get_value(
			"Sales Invoice",
			line.sales_invoice,
			["customer", "company", "docstatus", "outstanding_amount"],
			as_dict=True,
		)
		if not invoice or invoice.docstatus != 1 or invoice.company != doc.company:
			frappe.throw(
				_("Fila {0}: la factura {1} no está validada o es de otra compañía.").format(
					line.idx, line.sales_invoice
				)
			)
		if line.sales_invoice in seen:
			frappe.throw(_("Fila {0}: la factura {1} está repetida.").format(line.idx, line.sales_invoice))
		seen.add(line.sales_invoice)
		line.customer = invoice.customer
		if flt(line.amount) <= 0 or flt(line.amount) > flt(invoice.outstanding_amount) + 0.005:
			frappe.throw(
				_(
					"Fila {0}: el importe debe ser positivo y no superar el pendiente de la factura ({1})."
				).format(line.idx, invoice.outstanding_amount)
			)
		mandate = frappe.db.get_value(
			"ES Sepa Mandate",
			line.mandate,
			[
				"customer",
				"company",
				"scheme",
				"status",
				"mandate_type",
				"last_debit_date",
				"signature_date",
				"first_debit_done",
			],
			as_dict=True,
		)
		problem = None
		if not mandate:
			problem = _("no existe")
		elif mandate.status != "Activo" or is_expired(mandate.last_debit_date or mandate.signature_date):
			problem = _("no está activo")
		elif mandate.scheme != doc.scheme:
			problem = _("es del esquema {0} y la remesa es {1}").format(mandate.scheme, doc.scheme)
		elif mandate.customer != invoice.customer or mandate.company != doc.company:
			problem = _("es de otro cliente o de otra compañía")
		elif mandate.mandate_type == "Único" and mandate.first_debit_done:
			problem = _("es de un solo uso y ya se adeudó")
		if problem:
			frappe.throw(
				_(
					"Fila {0}: el mandato {1} {2}. Use un mandato activo del cliente y del esquema de la remesa."
				).format(line.idx, frappe.bold(line.mandate), problem),
				title=_("Mandato no válido"),
			)
		line.sequence = "OOFF" if mandate.mandate_type == "Único" else "RCUR"
	doc.total_amount = sum(flt(line.amount) for line in doc.lines)


def submit_batch(doc) -> None:
	check_role()
	check_parties([("Customer", line.customer) for line in doc.lines])
	company_name = frappe.get_cached_value("Company", doc.company, "company_name")
	account = bank_account_party(
		doc.bank_account, company_name, company_address(doc.company), sepa_creditor_id(doc.company)
	)
	initiating = xml.Party(
		name=company_name, iban=account.iban, identifier=presenter_id(doc.company, doc.bank_account)
	)
	message_id = f"{doc.name}-{frappe.generate_hash(length=6).upper()}"
	batch = xml.Batch(
		message_id=message_id,
		initiating_party=initiating,
		account=account,
		requested_date=getdate(doc.collection_date),
		scheme=doc.scheme,
	)
	for line in doc.lines:
		mandate = frappe.get_doc("ES Sepa Mandate", line.mandate)
		end_to_end = f"{doc.name}-{line.idx}"
		name = frappe.get_cached_value("Customer", line.customer, "customer_name")
		debtor = bank_account_party(mandate.bank_account, name, party_address("Customer", line.customer))
		batch.transactions.append(
			xml.Transaction(
				end_to_end_id=end_to_end,
				amount=xml.amount(line.amount),
				party=debtor,
				remittance=_("Factura {0}").format(line.sales_invoice),
				mandate_id=mandate.mandate_reference,
				mandate_date=getdate(mandate.signature_date),
				sequence=line.sequence,
			)
		)
		line.db_set({"end_to_end_id": end_to_end, "status": "Enviada"})

	content = xml.direct_debit(batch)
	doc.db_set(
		{
			"message_id": message_id,
			"sepa_file": attach(doc.doctype, doc.name, f"{doc.name}-{xml.PAIN_008}.xml", content),
		}
	)

	submit_payments = cint(frappe.get_cached_value("Company", doc.company, "es_sepa_submit_payments"))
	for line in doc.lines:
		payment = make_payment(doc, line)
		if submit_payments:
			payment.submit()
		line.db_set("payment_entry", payment.name)
		mandate = frappe.get_doc("ES Sepa Mandate", line.mandate)
		mandate.db_set({"last_debit_date": doc.collection_date, "first_debit_done": 1})


def make_payment(doc, line):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	ledger = frappe.get_cached_value("Bank Account", doc.bank_account, "account")
	payment = get_payment_entry(
		"Sales Invoice", line.sales_invoice, party_amount=flt(line.amount), bank_account=ledger
	)
	payment.update(
		{
			"posting_date": doc.collection_date,
			"paid_to": ledger,
			"bank_account": doc.bank_account,
			"reference_no": line.end_to_end_id,
			"reference_date": doc.collection_date,
			"es_end_to_end_id": line.end_to_end_id,
		}
	)
	if frappe.db.exists("Mode of Payment", DIRECT_DEBIT_MODE):
		payment.mode_of_payment = DIRECT_DEBIT_MODE
	payment.insert()
	return payment


def cancel_batch(doc) -> None:
	from erpnext_spain.es_sepa.status import undo_collection

	for line in doc.lines:
		undo_collection(line)
