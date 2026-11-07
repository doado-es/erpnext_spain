# Remesas SEPA de transferencias (pain.001) sobre la Payment Order nativa
# (spec 11 §4) y datos comunes de compañía y cuentas.

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from erpnext_spain.es_sepa import xml
from erpnext_spain.es_sepa.utils import (
	check_parties,
	clean_iban,
	creditor_identifier,
	is_valid_iban,
	party_address,
)
from erpnext_spain.utils.company import legal_name
from erpnext_spain.utils.gating import is_pgc_company

ALLOWED_ROLES = ("Accounts Manager", "System Manager")


def check_role() -> None:
	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Solo un usuario con rol Accounts Manager puede generar ficheros SEPA."), frappe.PermissionError
		)


def company_address(company: str) -> dict | None:
	"""Dirección de la compañía, priorizando la marcada como dirección de la compañía."""
	links = frappe.get_all(
		"Address",
		filters=[
			["Dynamic Link", "link_doctype", "=", "Company"],
			["Dynamic Link", "link_name", "=", company],
			["disabled", "=", 0],
		],
		pluck="name",
		order_by="is_your_company_address desc, is_primary_address desc",
		limit=1,
	)
	if not links:
		return None
	return frappe.get_cached_value(
		"Address", links[0], ["address_line1", "address_line2", "pincode", "city", "country"], as_dict=True
	)


def bank_account_party(
	bank_account: str, name: str, address: dict | None, identifier: str | None = None
) -> xml.Party:
	account = frappe.get_cached_value(
		"Bank Account", bank_account, ["iban", "bank", "account_name"], as_dict=True
	)
	if not account or not is_valid_iban(account.iban):
		frappe.throw(
			_("La cuenta bancaria {0} no tiene un IBAN válido. Corríjalo en la cuenta bancaria.").format(
				frappe.bold(bank_account)
			),
			title=_("IBAN no válido"),
		)
	bic = frappe.get_cached_value("Bank", account.bank, "swift_number") if account.bank else None
	return xml.Party(
		name=name, iban=clean_iban(account.iban), bic=bic, address=address, identifier=identifier
	)


def company_tax_id(company: str) -> str:
	tax_id = frappe.get_cached_value("Company", company, "tax_id")
	if not tax_id:
		frappe.throw(
			_("La compañía {0} no tiene NIF. Indíquelo en la ficha de la compañía.").format(
				frappe.bold(company)
			)
		)
	return tax_id


def presenter_id(company: str, bank_account: str, norm_name: str | None = None) -> str:
	"""Identificador del presentador: NIF de la compañía + sufijo de la norma en esa cuenta."""
	from erpnext_spain.es_sepa.bank_account import TRANSFERS, norm

	return f"{company_tax_id(company)}{norm(bank_account, norm_name or TRANSFERS).suffix or '000'}"


def sepa_creditor_id(company: str, bank_account: str) -> str:
	"""Identificador de acreedor SEPA con el sufijo de la norma de adeudos de la cuenta."""
	from erpnext_spain.es_sepa.bank_account import DIRECT_DEBITS, norm

	return creditor_identifier(company_tax_id(company), norm(bank_account, DIRECT_DEBITS).suffix or "000")


def attach(doctype: str, name: str, file_name: str, content: bytes) -> str:
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"is_private": 1,
			"content": content,
		}
	)
	file.insert(ignore_permissions=True)
	return file.file_url


def supplier_bank_account(row) -> str:
	if row.bank_account:
		return row.bank_account
	account = frappe.db.get_value(
		"Bank Account", {"party_type": "Supplier", "party": row.supplier, "is_default": 1}, "name"
	) or frappe.db.get_value("Bank Account", {"party_type": "Supplier", "party": row.supplier}, "name")
	if not account:
		frappe.throw(
			_("El proveedor {0} no tiene cuenta bancaria. Créela con su IBAN.").format(
				frappe.bold(row.supplier)
			),
			title=_("Falta la cuenta del beneficiario"),
		)
	return account


@frappe.whitelist(methods=["POST"])
def generate_credit_transfer(payment_order: str) -> str:
	"""Genera el pain.001.001.09 de una Payment Order validada y lo adjunta."""
	check_role()
	order = frappe.get_doc("Payment Order", payment_order)
	order.check_permission("write")
	if order.docstatus != 1:
		frappe.throw(
			_("Valide la orden de pago {0} antes de generar el fichero.").format(frappe.bold(payment_order))
		)
	if not is_pgc_company(order.company):
		frappe.throw(_("La compañía {0} no tiene el plan PGC aplicado.").format(frappe.bold(order.company)))
	if not order.company_bank_account:
		frappe.throw(_("Indique la cuenta bancaria de la compañía en la orden de pago."))

	check_parties([("Supplier", row.supplier) for row in order.references])
	company_name = legal_name(order.company)
	account = bank_account_party(
		order.company_bank_account,
		company_name,
		company_address(order.company),
		presenter_id(order.company, order.company_bank_account),
	)
	message_id = order.get("es_sepa_message_id") or f"{order.name}-{frappe.generate_hash(length=6).upper()}"
	batch = xml.Batch(
		message_id=message_id,
		initiating_party=account,
		account=account,
		requested_date=getdate(order.get("es_sepa_execution_date") or nowdate()),
		priority="HIGH" if order.get("es_sepa_priority") == "Urgente" else "NORM",
		instant=bool(order.get("es_sepa_instant")),
	)
	for row in order.references:
		end_to_end = row.get("es_end_to_end_id") or f"{order.name}-{row.idx}"
		name = frappe.get_cached_value("Supplier", row.supplier, "supplier_name")
		beneficiary = bank_account_party(
			supplier_bank_account(row), name, party_address("Supplier", row.supplier)
		)
		batch.transactions.append(
			xml.Transaction(
				end_to_end_id=end_to_end,
				amount=xml.amount(row.amount),
				party=beneficiary,
				remittance=remittance(row),
			)
		)
		row.db_set("es_end_to_end_id", end_to_end)
		row.db_set("es_sepa_status", _("Enviada"))
		if row.reference_doctype == "Payment Entry":
			frappe.db.set_value("Payment Entry", row.reference_name, "es_end_to_end_id", end_to_end)

	content = xml.credit_transfer(batch)
	url = attach("Payment Order", order.name, f"{order.name}-{xml.PAIN_001}.xml", content)
	order.db_set({"es_sepa_message_id": message_id, "es_sepa_file": url})
	return url


def remittance(row) -> str:
	if row.reference_doctype == "Payment Entry":
		bills = frappe.get_all(
			"Payment Entry Reference",
			filters={"parent": row.reference_name, "reference_doctype": "Purchase Invoice"},
			pluck="reference_name",
		)
		numbers = [frappe.db.get_value("Purchase Invoice", bill, "bill_no") or bill for bill in bills]
		if numbers:
			return _("Pago facturas {0}").format(", ".join(numbers))
	return _("Pago {0}").format(row.reference_name)


@frappe.whitelist(methods=["POST"])
def import_credit_transfer_status(payment_order: str, file_url: str) -> dict:
	"""Importa el pain.002 de una orden de pago: estado por operación."""
	from erpnext_spain.es_sepa.status import read_file

	check_role()
	order = frappe.get_doc("Payment Order", payment_order)
	order.check_permission("write")
	report = xml.parse_status_report(read_file(file_url))
	counts = {"accepted": 0, "rejected": 0}
	for row in order.references:
		status, reason = report["transactions"].get(row.es_end_to_end_id, (report["group_status"], None))
		if status in ("RJCT",):
			row.db_set("es_sepa_status", _("Rechazada ({0})").format(reason or "-"))
			counts["rejected"] += 1
		elif status:
			row.db_set("es_sepa_status", status)
			counts["accepted"] += 1
	return counts
