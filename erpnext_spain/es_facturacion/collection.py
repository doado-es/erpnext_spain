# Situación de cobro de las facturas de venta (spec 05 §4).
#
# No se toca el `status` nativo: el custom field `es_collection_status` (Normal ·
# Dudoso cobro · Pérdida) y cuatro acciones que contabilizan con Journal Entry
# nativo, con tercero, referencia a la factura y dimensiones contables (R9).
# Esquema **[revisar con un contable]**:
#
# | Acción                    | Asiento                                            |
# |---------------------------|----------------------------------------------------|
# | Pasar a dudoso cobro      | 4360 (cliente) a 4300 (cliente, ref. factura)      |
# | Dotar deterioro           | 6940 a 4900                                        |
# | Declarar pérdida          | 6500 a 4360 (cliente) y, si hubo deterioro, 4900 a 7940 |
# | Recuperar (dudoso cobro)  | 4300 (cliente, ref. factura) a 4360 y, si hubo deterioro, 4900 a 7940 |
#
# El paso a la 4360 deja la factura sin pendiente y el saldo en un asiento del
# cliente contra la 4360 (cuenta de tipo Receivable): el informe Accounts
# Receivable lo sigue mostrando y un cobro posterior se asigna a ese asiento.

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt, nowdate

from erpnext_spain.utils.gating import is_pgc_company

NORMAL = "Normal"
DOUBTFUL = "Dudoso cobro"
LOSS = "Pérdida"
STATUSES = (NORMAL, DOUBTFUL, LOSS)

ACCOUNTS = {
	"receivable": "4300",
	"doubtful": "4360",
	"impairment": "4900",
	"impairment_expense": "6940",
	"loss_expense": "6500",
	"impairment_reversal": "7940",
}
ALLOWED_ROLES = ("Accounts Manager", "System Manager")


def account(company: str, key: str) -> str:
	number = ACCOUNTS[key]
	name = frappe.db.get_value(
		"Account", {"company": company, "account_number": number, "is_group": 0}, "name"
	)
	if not name:
		frappe.throw(
			_("Falta la cuenta {0} en la compañía {1}. Créela en el plan de cuentas (rama del PGC).").format(
				frappe.bold(number), frappe.bold(company)
			)
		)
	return name


def get_invoice(invoice: str):
	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Solo un usuario con rol {0} puede cambiar la situación de cobro.").format(
				_(" o ").join(_(role) for role in ALLOWED_ROLES)
			),
			frappe.PermissionError,
		)
	doc = frappe.get_doc("Sales Invoice", invoice)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("La factura {0} no está validada.").format(frappe.bold(invoice)))
	if not is_pgc_company(doc.company):
		frappe.throw(
			_("La compañía {0} no tiene el plan PGC aplicado: la situación de cobro usa sus cuentas.").format(
				frappe.bold(doc.company)
			)
		)
	return doc


def dimensions(doc) -> dict:
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions

	values = {
		"cost_center": doc.cost_center or frappe.get_cached_value("Company", doc.company, "cost_center")
	}
	if doc.get("project"):
		values["project"] = doc.project
	for dimension in get_accounting_dimensions():
		if doc.get(dimension):
			values[dimension] = doc.get(dimension)
	return values


def make_entry(doc, remark: str, lines: list[dict]) -> str:
	entry = frappe.new_doc("Journal Entry")
	entry.update(
		{
			"voucher_type": "Journal Entry",
			"company": doc.company,
			"posting_date": nowdate(),
			"user_remark": remark,
		}
	)
	extra = dimensions(doc)
	for line in lines:
		entry.append("accounts", {**extra, **line})
	entry.insert()
	entry.submit()
	return entry.name


def party(doc) -> dict:
	return {"party_type": "Customer", "party": doc.customer}


def doubtful_balance(doc) -> float:
	"""Saldo que queda en la 4360 del asiento de dudoso cobro de la factura, según
	el Payment Ledger (los cobros asignados a ese asiento lo reducen)."""
	if not doc.es_doubtful_entry:
		return 0
	ple = frappe.qb.DocType("Payment Ledger Entry")
	result = (
		frappe.qb.from_(ple)
		.select(Sum(ple.amount))
		.where(ple.against_voucher_type == "Journal Entry")
		.where(ple.against_voucher_no == doc.es_doubtful_entry)
		.where(ple.account == account(doc.company, "doubtful"))
		.where(ple.party == doc.customer)
		.where(ple.delinked == 0)
	).run()
	return flt(result[0][0]) if result else 0


def set_status(doc, status: str, **links) -> None:
	doc.db_set({"es_collection_status": status, **links}, notify=True)
	doc.add_comment("Info", _("Situación de cobro: {0}.").format(_(status)))


@frappe.whitelist(methods=["POST"])
def mark_doubtful(invoice: str) -> str:
	doc = get_invoice(invoice)
	if (doc.es_collection_status or NORMAL) != NORMAL:
		frappe.throw(
			_("La factura {0} ya está en {1}.").format(frappe.bold(invoice), _(doc.es_collection_status))
		)
	amount = flt(doc.outstanding_amount)
	if amount <= 0:
		frappe.throw(_("La factura {0} no tiene importe pendiente de cobro.").format(frappe.bold(invoice)))
	entry = make_entry(
		doc,
		_("Paso a dudoso cobro de la factura {0}").format(invoice),
		[
			{"account": account(doc.company, "doubtful"), **party(doc), "debit_in_account_currency": amount},
			{
				"account": doc.debit_to,
				**party(doc),
				"credit_in_account_currency": amount,
				"reference_type": "Sales Invoice",
				"reference_name": invoice,
			},
		],
	)
	set_status(doc, DOUBTFUL, es_doubtful_entry=entry, es_doubtful_amount=amount)
	return entry


@frappe.whitelist(methods=["POST"])
def provision_impairment(invoice: str) -> str:
	doc = get_invoice(invoice)
	if doc.es_collection_status != DOUBTFUL:
		frappe.throw(_("Primero pase la factura {0} a dudoso cobro.").format(frappe.bold(invoice)))
	if doc.es_impairment_entry:
		frappe.throw(_("El deterioro de la factura {0} ya está dotado.").format(frappe.bold(invoice)))
	amount = doubtful_balance(doc)
	if amount <= 0:
		frappe.throw(_("La factura {0} ya no tiene saldo de dudoso cobro.").format(frappe.bold(invoice)))
	entry = make_entry(
		doc,
		_("Deterioro del crédito de la factura {0}").format(invoice),
		[
			{"account": account(doc.company, "impairment_expense"), "debit_in_account_currency": amount},
			{"account": account(doc.company, "impairment"), "credit_in_account_currency": amount},
		],
	)
	doc.db_set({"es_impairment_entry": entry, "es_impairment_amount": amount}, notify=True)
	return entry


def reverse_impairment_lines(doc) -> list[dict]:
	amount = flt(doc.es_impairment_amount)
	if not doc.es_impairment_entry or amount <= 0:
		return []
	return [
		{"account": account(doc.company, "impairment"), "debit_in_account_currency": amount},
		{"account": account(doc.company, "impairment_reversal"), "credit_in_account_currency": amount},
	]


@frappe.whitelist(methods=["POST"])
def declare_loss(invoice: str) -> str:
	doc = get_invoice(invoice)
	if doc.es_collection_status != DOUBTFUL:
		frappe.throw(_("Solo se declara la pérdida de una factura en dudoso cobro."))
	amount = doubtful_balance(doc)
	if amount <= 0:
		frappe.throw(_("La factura {0} ya no tiene saldo de dudoso cobro.").format(frappe.bold(invoice)))
	entry = make_entry(
		doc,
		_("Pérdida definitiva del crédito de la factura {0}").format(invoice),
		[
			{"account": account(doc.company, "loss_expense"), "debit_in_account_currency": amount},
			{
				"account": account(doc.company, "doubtful"),
				**party(doc),
				"credit_in_account_currency": amount,
				"reference_type": "Journal Entry",
				"reference_name": doc.es_doubtful_entry,
			},
			*reverse_impairment_lines(doc),
		],
	)
	set_status(doc, LOSS, es_loss_entry=entry)
	return entry


@frappe.whitelist(methods=["POST"])
def recover(invoice: str) -> str:
	"""Vuelve a situación normal una factura en dudoso cobro (el cliente va a pagar)."""
	doc = get_invoice(invoice)
	if doc.es_collection_status != DOUBTFUL:
		frappe.throw(
			_(
				"Solo se recupera una factura en dudoso cobro. Un cobro posterior a la pérdida"
				" definitiva se registra como ingreso (cuenta 778) con un asiento manual."
			)
		)
	amount = doubtful_balance(doc)
	if amount <= 0:
		frappe.throw(_("La factura {0} ya no tiene saldo de dudoso cobro.").format(frappe.bold(invoice)))
	entry = make_entry(
		doc,
		_("Recuperación del crédito de la factura {0}").format(invoice),
		[
			{
				"account": doc.debit_to,
				**party(doc),
				"debit_in_account_currency": amount,
				"reference_type": "Sales Invoice",
				"reference_name": invoice,
			},
			{
				"account": account(doc.company, "doubtful"),
				**party(doc),
				"credit_in_account_currency": amount,
				"reference_type": "Journal Entry",
				"reference_name": doc.es_doubtful_entry,
			},
			*reverse_impairment_lines(doc),
		],
	)
	set_status(doc, NORMAL, es_recovery_entry=entry)
	return entry


def flag_doubtful_candidates() -> None:
	"""Job diario: avisa de las facturas vencidas hace más de `es_doubtful_months`
	meses (no contabiliza nada)."""
	from frappe.utils import add_months

	for company, months in frappe.get_all(
		"Company",
		filters={"es_pgc_applied": 1, "es_doubtful_months": [">", 0]},
		fields=["name", "es_doubtful_months"],
		as_list=True,
	):
		limit = add_months(nowdate(), -int(months))
		invoices = frappe.get_all(
			"Sales Invoice",
			filters={
				"company": company,
				"docstatus": 1,
				"outstanding_amount": [">", 0],
				"due_date": ["<", limit],
				"es_collection_status": ["in", ["", None, NORMAL]],
			},
			pluck="name",
		)
		if not invoices:
			continue
		for user in frappe.get_all(
			"Has Role", filters={"role": "Accounts Manager", "parenttype": "User"}, pluck="parent"
		):
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": user,
					"type": "Alert",
					"document_type": "Company",
					"document_name": company,
					"subject": _(
						"{0}: {1} facturas vencidas hace más de {2} meses (candidatas a dudoso cobro)"
					).format(company, len(invoices), months),
				}
			).insert(ignore_permissions=True)
