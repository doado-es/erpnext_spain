# Cuenta bancaria: normas de la compañía y mandato SEPA del cliente (spec 11-12).

import re

import frappe
from frappe import _
from frappe.utils import add_months, getdate, nowdate

TRANSFERS, DIRECT_DEBITS, CONFIRMING = "Transferencias SEPA", "Adeudos SEPA", "Confirming"
MANDATE_REFERENCE = re.compile(r"^[A-Za-z0-9+?/\-:().,' ]{1,35}$")
EXPIRY_MONTHS = 36


def norm(bank_account: str, name: str):
	"""Fila de la norma `name` de una cuenta de la compañía, o error con remedio."""
	row = frappe.db.get_value(
		"ES Bank Account Norm",
		{"parent": bank_account, "parenttype": "Bank Account", "norm": name},
		["suffix", "contract_number", "limit", "remittance_type", "accounting_option", "debt_account"],
		as_dict=True,
	)
	if not row:
		frappe.throw(
			_(
				"La cuenta bancaria {0} no tiene configurada la norma «{1}». Añádala en la cuenta, sección"
				" «Normas bancarias», con el sufijo (y el contrato en confirming) que le ha dado el banco."
			).format(frappe.bold(bank_account), _(name)),
			title=_("Falta la norma bancaria"),
		)
	return row


def is_expired(reference_date) -> bool:
	"""Caducidad por falta de uso: 36 meses sin adeudos **[revisar]**."""
	return bool(reference_date) and getdate(add_months(reference_date, EXPIRY_MONTHS)) < getdate(nowdate())


def validate(doc, method=None) -> None:
	"""doc_event de Bank Account: normas sin repetir y mandato coherente."""
	seen = set()
	for row in doc.get("es_norms") or []:
		if row.norm in seen:
			frappe.throw(_("La norma {0} está repetida en la cuenta {1}.").format(_(row.norm), doc.name))
		seen.add(row.norm)
	if not doc.get("es_sepa_scheme"):
		return
	if doc.party_type != "Customer" or doc.is_company_account:
		frappe.throw(_("El mandato SEPA solo se informa en cuentas bancarias de clientes."))
	reference = (doc.es_sepa_mandate_reference or "").strip()
	if not MANDATE_REFERENCE.match(reference):
		frappe.throw(
			_(
				"La referencia del mandato {0} no es válida: hasta 35 caracteres entre letras, números"
				" y + ? / - : ( ) . , '"
			).format(frappe.bold(reference or "-"))
		)
	duplicate = frappe.db.get_value(
		"Bank Account", {"es_sepa_mandate_reference": reference, "name": ["!=", doc.name or ""]}, "name"
	)
	if duplicate:
		frappe.throw(
			_("La referencia de mandato {0} ya se usa en la cuenta {1}: debe ser única.").format(
				frappe.bold(reference), duplicate
			)
		)
	if doc.es_sepa_mandate_status == "Activo" and is_expired(
		doc.es_sepa_last_debit or doc.es_sepa_mandate_date
	):
		doc.es_sepa_mandate_status = "Caducado"
