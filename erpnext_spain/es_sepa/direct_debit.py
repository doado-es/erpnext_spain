# Remesas de adeudos SEPA (spec 11 §5): selección de facturas, validaciones,
# fichero pain.008 y cobros.

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, getdate

from erpnext_spain.es_sepa import effects, xml
from erpnext_spain.es_sepa.bank_account import DIRECT_DEBITS, is_expired
from erpnext_spain.es_sepa.credit_transfer import (
	attach,
	bank_account_party,
	check_role,
	company_address,
	presenter_id,
	sepa_creditor_id,
)
from erpnext_spain.es_sepa.utils import check_parties, party_address
from erpnext_spain.utils.company import legal_name
from erpnext_spain.utils.gating import is_pgc_company

DIRECT_DEBIT_MODE = "Domiciliación bancaria"


MANDATE_FIELDS = [
	"party_type",
	"party",
	"es_sepa_scheme",
	"es_sepa_mandate_status",
	"es_sepa_mandate_type",
	"es_sepa_mandate_reference",
	"es_sepa_mandate_date",
	"es_sepa_last_debit",
	"es_sepa_first_debit_done",
]


def mandate_account(customer: str, scheme: str) -> str | None:
	"""Cuenta bancaria del cliente con mandato activo del esquema (primero la
	cuenta por defecto del cliente)."""
	default = frappe.get_cached_value("Customer", customer, "default_bank_account")
	candidates = [default] if default else []
	candidates += frappe.get_all(
		"Bank Account",
		filters={"party_type": "Customer", "party": customer, "es_sepa_scheme": scheme, "disabled": 0},
		pluck="name",
		order_by="is_default desc, creation",
	)
	for name in candidates:
		values = frappe.db.get_value("Bank Account", name, MANDATE_FIELDS, as_dict=True)
		if values and values.es_sepa_scheme == scheme and values.es_sepa_mandate_status == "Activo":
			return name
	return None


@frappe.whitelist()
def get_effects(
	company: str,
	scheme: str = "CORE",
	customers: list | str | None = None,
	payment_terms_templates: list | str | None = None,
	from_due_date: str | None = None,
	to_due_date: str | None = None,
	min_amount: float | None = None,
	max_amount: float | None = None,
	batch: str | None = None,
) -> list[dict]:
	"""Efectos pendientes que se pueden adeudar: vencimientos de facturas validadas
	con forma de pago «Domiciliación bancaria» (o sin forma de pago) de clientes con
	mandato activo del esquema, sin los que ya están en otras remesas en curso."""
	frappe.has_permission("Sales Invoice", "read", throw=True)
	frappe.has_permission("ES Sepa Direct Debit Batch", "read", throw=True)
	found = effects.pending_effects(
		"Sales Invoice",
		"customer",
		company,
		["customer_name"],
		parties=effects.as_list(customers),
		payment_terms_templates=effects.as_list(payment_terms_templates),
	)
	found = [e for e in found if e["mode_of_payment"] in (None, "", DIRECT_DEBIT_MODE)]
	found = effects.in_range(
		effects.subtract_reserved(found, reserved_effects(batch)),
		from_due_date,
		to_due_date,
		min_amount,
		max_amount,
	)
	mandates: dict[str, str | None] = {}
	rows = []
	for effect in found:
		customer = effect["customer"]
		if customer not in mandates:
			mandates[customer] = mandate_account(customer, scheme)
		if not mandates[customer]:
			continue
		rows.append(
			{
				"sales_invoice": effect["invoice"],
				"customer": customer,
				"customer_name": effect["customer_name"],
				"payment_term": effect["payment_term"],
				"due_date": effect["due_date"],
				"amount": effect["amount"],
				"bank_account": mandates[customer],
				"iban": frappe.get_cached_value("Bank Account", mandates[customer], "iban"),
			}
		)
	return rows


def reserved_effects(exclude_batch: str | None = None) -> dict[tuple, float]:
	"""Importe de cada efecto (factura, vencimiento) que ya está en una remesa en
	curso: en borrador, o validada con el cobro sin validar. Los rechazados y
	devueltos vuelven a estar disponibles."""
	batch = frappe.qb.DocType("ES Sepa Direct Debit Batch")
	line = frappe.qb.DocType("ES Sepa Direct Debit Line")
	payment = frappe.qb.DocType("Payment Entry")
	query = (
		frappe.qb.from_(line)
		.join(batch)
		.on(line.parent == batch.name)
		.left_join(payment)
		.on(line.payment_entry == payment.name)
		.select(line.sales_invoice, line.payment_term, line.amount)
		.where(
			(line.parenttype == "ES Sepa Direct Debit Batch")
			& (batch.docstatus < 2)
			& (line.status.isnull() | line.status.notin(["Rechazada", "Devuelta"]))
			& (payment.name.isnull() | (payment.docstatus == 0))
		)
	)
	if exclude_batch:
		query = query.where(batch.name != exclude_batch)
	reserved: dict[tuple, float] = {}
	for invoice, term, amount in query.run():
		key = (invoice, term or "")
		reserved[key] = reserved.get(key, 0) + flt(amount)
	return reserved


def validate_batch(doc) -> None:
	if not is_pgc_company(doc.company):
		frappe.throw(_("La compañía {0} no tiene el plan PGC aplicado.").format(frappe.bold(doc.company)))
	account = frappe.db.get_value(
		"Bank Account", doc.bank_account, ["company", "is_company_account"], as_dict=True
	)
	if not account or not account.is_company_account or account.company != doc.company:
		frappe.throw(
			_("La cuenta de abono {0} no es una cuenta de la compañía.").format(frappe.bold(doc.bank_account))
		)
	seen = set()
	per_invoice: dict[str, float] = {}
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
		key = (line.sales_invoice, line.payment_term or "")
		if key in seen:
			frappe.throw(
				_("Fila {0}: el efecto de la factura {1} está repetido.").format(line.idx, line.sales_invoice)
			)
		seen.add(key)
		line.customer = invoice.customer
		per_invoice[line.sales_invoice] = per_invoice.get(line.sales_invoice, 0) + flt(line.amount)
		if flt(line.amount) <= 0 or per_invoice[line.sales_invoice] > flt(invoice.outstanding_amount) + 0.005:
			frappe.throw(
				_(
					"Fila {0}: el importe debe ser positivo y los efectos de la factura {1} no pueden superar"
					" su pendiente ({2})."
				).format(line.idx, line.sales_invoice, invoice.outstanding_amount)
			)
		mandate = frappe.db.get_value("Bank Account", line.bank_account, MANDATE_FIELDS, as_dict=True)
		problem = None
		if not mandate or not mandate.es_sepa_scheme:
			problem = _("no tiene mandato SEPA")
		elif mandate.es_sepa_mandate_status != "Activo" or is_expired(
			mandate.es_sepa_last_debit or mandate.es_sepa_mandate_date
		):
			problem = _("tiene el mandato cancelado o caducado")
		elif mandate.es_sepa_scheme != doc.scheme:
			problem = _("tiene un mandato {0} y la remesa es {1}").format(mandate.es_sepa_scheme, doc.scheme)
		elif mandate.party_type != "Customer" or mandate.party != invoice.customer:
			problem = _("no es del cliente de la factura")
		elif mandate.es_sepa_mandate_type == "Único" and mandate.es_sepa_first_debit_done:
			problem = _("tiene un mandato de un solo uso ya adeudado")
		if problem:
			frappe.throw(
				_(
					"Fila {0}: la cuenta {1} {2}. Use una cuenta del cliente con mandato activo del esquema de la remesa."
				).format(line.idx, frappe.bold(line.bank_account), problem),
				title=_("Mandato no válido"),
			)
		line.sequence = "OOFF" if mandate.es_sepa_mandate_type == "Único" else "RCUR"
	doc.total_amount = sum(flt(line.amount) for line in doc.lines)


def submit_batch(doc) -> None:
	check_role()
	check_parties([("Customer", line.customer) for line in doc.lines])
	company_name = legal_name(doc.company)
	account = bank_account_party(
		doc.bank_account,
		company_name,
		company_address(doc.company),
		sepa_creditor_id(doc.company, doc.bank_account),
	)
	initiating = xml.Party(
		name=company_name,
		iban=account.iban,
		identifier=presenter_id(doc.company, doc.bank_account, DIRECT_DEBITS),
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
		mandate = frappe.db.get_value("Bank Account", line.bank_account, MANDATE_FIELDS, as_dict=True)
		end_to_end = f"{doc.name}-{line.idx}"
		name = frappe.get_cached_value("Customer", line.customer, "customer_name")
		debtor = bank_account_party(line.bank_account, name, party_address("Customer", line.customer))
		batch.transactions.append(
			xml.Transaction(
				end_to_end_id=end_to_end,
				amount=xml.amount(line.amount),
				party=debtor,
				remittance=(
					_("Factura {0}, vencimiento {1}").format(line.sales_invoice, formatdate(line.due_date))
					if line.due_date
					else _("Factura {0}").format(line.sales_invoice)
				),
				mandate_id=mandate.es_sepa_mandate_reference,
				mandate_date=getdate(mandate.es_sepa_mandate_date),
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
		frappe.db.set_value(
			"Bank Account",
			line.bank_account,
			{"es_sepa_last_debit": doc.collection_date, "es_sepa_first_debit_done": 1},
		)


def make_payment(doc, line):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	ledger = frappe.get_cached_value("Bank Account", doc.bank_account, "account")
	payment = get_payment_entry(
		"Sales Invoice", line.sales_invoice, party_amount=flt(line.amount), bank_account=ledger
	)
	allocate_to_effect(payment, line.sales_invoice, line.payment_term, flt(line.amount))
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


def allocate_to_effect(payment, invoice: str, payment_term: str | None, amount: float) -> None:
	"""Deja una sola referencia: la factura y, si lo hay, el vencimiento del efecto.
	Con el vencimiento, ERPNext descuenta el pago del pendiente de ese plazo."""
	references = [r for r in payment.references if r.reference_name == invoice]
	reference = next(
		(r for r in references if payment_term and r.payment_term == payment_term),
		references[0] if references else None,
	)
	if not reference:
		return
	reference.allocated_amount = amount
	if payment_term:
		reference.payment_term = payment_term
	payment.set("references", [reference])


def cancel_batch(doc) -> None:
	from erpnext_spain.es_sepa.status import undo_collection

	for line in doc.lines:
		undo_collection(line)
