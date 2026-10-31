# Importación de Norma 43 a Bank Transaction (spec 13 §2) y emparejamiento
# automático de movimientos (spec 13 §4).

import re

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_spain.es_bancos import norma43
from erpnext_spain.utils.gating import is_pgc_company

ALLOWED_ROLES = ("Accounts Manager", "Accounts User", "System Manager")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{5,34}")


def company_accounts(company: str) -> dict[str, str]:
	"""Cuentas bancarias de la compañía por entidad + oficina + cuenta (sin DC)."""
	result = {}
	for name, iban in frappe.get_all(
		"Bank Account",
		filters={"company": company, "is_company_account": 1},
		fields=["name", "iban"],
		as_list=True,
	):
		iban = re.sub(r"\s", "", iban or "").upper()
		if iban.startswith("ES") and len(iban) == 24:
			result[iban[4:12] + iban[14:24]] = name
	return result


def import_norma43(company: str, content: bytes) -> dict:
	if not is_pgc_company(company):
		frappe.throw(_("La compañía {0} no tiene el plan PGC aplicado.").format(frappe.bold(company)))
	try:
		blocks = norma43.parse(content)
	except (norma43.Norma43Error, ValueError) as error:
		frappe.throw(
			_("El fichero no es un Norma 43 válido: {0}").format(frappe.utils.escape_html(str(error))),
			title=_("Norma 43"),
		)
	accounts = company_accounts(company)
	currency = frappe.get_cached_value("Company", company, "default_currency")
	summary = {"created": 0, "duplicates": 0, "accounts": [], "errors": []}
	for block in blocks:
		bank_account = accounts.get(block.key)
		label = f"{block.bank} {block.office} {block.account}"
		if not bank_account:
			summary["errors"].append(
				_("Cuenta {0} ({1}): no es una cuenta bancaria de {2}; no se ha importado.").format(
					label, block.name, company
				)
			)
			continue
		if block.errors:
			summary["errors"].append(
				_("Cuenta {0}: {1}; no se ha importado.").format(label, "; ".join(block.errors))
			)
			continue
		created = 0
		for movement in block.movements:
			tid = norma43.transaction_id(block, movement)
			if frappe.db.exists(
				"Bank Transaction",
				{"transaction_id": tid, "bank_account": bank_account, "docstatus": ["<", 2]},
			):
				summary["duplicates"] += 1
				continue
			amount = flt(movement.amount)
			transaction = frappe.get_doc(
				{
					"doctype": "Bank Transaction",
					"date": movement.operation_date,
					"company": company,
					"bank_account": bank_account,
					"currency": currency,
					"deposit": amount if amount > 0 else 0,
					"withdrawal": -amount if amount < 0 else 0,
					"description": movement.description or movement.reference,
					"reference_number": " ".join(
						part for part in (movement.reference, movement.document) if part
					),
					"transaction_id": tid,
					"transaction_type": movement.common_concept,
				}
			)
			transaction.insert()
			transaction.submit()
			created += 1
		summary["created"] += created
		summary["accounts"].append(
			{"bank_account": bank_account, "created": created, "closing_balance": flt(block.closing)}
		)
	return summary


# --- emparejamiento (doc_event de Bank Transaction) -----------------------------------


def validate_bank_transaction(doc, method=None) -> None:
	"""Propone el tercero por el IBAN y casa el pago por el EndToEndId SEPA."""
	if not is_pgc_company(doc.company):
		return
	if not doc.party and doc.get("bank_party_iban"):
		set_party_from_iban(doc)
	if doc.docstatus == 0 and not doc.get("payment_entries"):
		match_end_to_end(doc)


def set_party_from_iban(doc) -> None:
	iban = re.sub(r"\s", "", doc.bank_party_iban).upper()
	party = frappe.db.get_value(
		"Bank Account",
		{"iban": iban, "is_company_account": 0, "party_type": ["in", ["Customer", "Supplier"]]},
		["party_type", "party"],
	)
	if party:
		doc.party_type, doc.party = party


def match_end_to_end(doc) -> None:
	text = " ".join(filter(None, (doc.reference_number, doc.description)))
	tokens = set(TOKEN.findall(text))
	if not tokens:
		return
	payments = frappe.get_all(
		"Payment Entry",
		filters={
			"es_end_to_end_id": ["in", list(tokens)],
			"docstatus": 1,
			"company": doc.company,
			"clearance_date": ["is", "not set"],
		},
		fields=["name", "paid_amount", "received_amount", "payment_type", "party_type", "party"],
	)
	if not payments:
		return
	# Un adeudo casa con su cobro; un cargo de confirming, con todos los pagos de la
	# remesa (comparten referencia, spec 12). Solo si los importes cuadran.
	amount = flt(doc.deposit) or flt(doc.withdrawal)
	expected = sum(flt(p.received_amount if p.payment_type == "Receive" else p.paid_amount) for p in payments)
	if abs(amount - expected) > 0.005:
		return
	if len(payments) == 1:
		doc.party_type, doc.party = payments[0].party_type, payments[0].party
	for payment in payments:
		doc.append(
			"payment_entries",
			{
				"payment_document": "Payment Entry",
				"payment_entry": payment.name,
				"allocated_amount": 0.0,
				"reconciliation_type": "Matched",
			},
		)


@frappe.whitelist(methods=["POST"])
def run_norma43_import(name: str) -> dict:
	"""Procesa una ES Norma43 Import y guarda el resultado en ella."""
	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("No tiene permiso para importar extractos."), frappe.PermissionError)
	doc = frappe.get_doc("ES Norma43 Import", name)
	doc.check_permission("write")
	frappe.has_permission("Bank Transaction", "create", throw=True)
	file = frappe.get_doc("File", {"file_url": doc.norma43_file})
	content = file.get_content()
	summary = import_norma43(
		doc.company, content if isinstance(content, bytes) else content.encode("latin-1")
	)
	doc.db_set(
		{
			"status": "Con errores" if summary["errors"] else "Importado",
			"created_transactions": summary["created"],
			"duplicates": summary["duplicates"],
			"import_log": "\n".join(
				[
					*[
						_("{0}: {1} movimientos nuevos, saldo final {2}").format(
							a["bank_account"], a["created"], a["closing_balance"]
						)
						for a in summary["accounts"]
					],
					*summary["errors"],
				]
			),
		}
	)
	return summary
