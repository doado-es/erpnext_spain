# Clasificación fiscal de las filas de impuestos al validar la factura (spec 03 §5).
#
# Regional override de `erpnext.controllers.accounts_controller.validate_regional`
# (ERPNext lo llama con `frappe.flags.company` fijado, así que la región es el
# país de la compañía).
# 1. Fila sin clasificar + plantilla en la factura: se copia la clasificación de
#    la fila equivalente de la plantilla (misma cuenta y tipo de cargo). Nunca se
#    pisa lo informado.
# 2. Con `es_require_tax_classification` en la compañía, al validar (submit) la
#    factura falla si una fila de IVA o recargo no tiene calificación y tipo de
#    operación (y en compras, deducibilidad) o una retención no tiene clave. El
#    borrador se guarda igual.

import frappe
from frappe import _

from erpnext_spain.es_impuestos.codes import TAX_TYPES
from erpnext_spain.utils.gating import is_pgc_company

INVOICE_DOCTYPES = {
	"Sales Invoice": "Sales Taxes and Charges Template",
	"Purchase Invoice": "Purchase Taxes and Charges Template",
}
COMMON_FIELDS = (
	"es_tax_type",
	"es_vat_classification",
	"es_operation_type",
	"es_regime_key",
	"es_withholding_key",
)
PURCHASE_FIELDS = ("es_deductibility", "es_self_assessed")
VAT_TYPES = (TAX_TYPES["IVA"], TAX_TYPES["RE"])


def validate_regional(doc) -> None:
	if doc.doctype not in INVOICE_DOCTYPES or not is_pgc_company(doc.company):
		return
	copy_classification_from_template(doc)
	if doc.docstatus == 1 and frappe.get_cached_value(
		"Company", doc.company, "es_require_tax_classification"
	):
		check_classification(doc)


def classification_fields(doctype: str) -> tuple[str, ...]:
	return COMMON_FIELDS + (PURCHASE_FIELDS if doctype == "Purchase Invoice" else ())


def copy_classification_from_template(doc) -> None:
	if not doc.get("taxes_and_charges") or not doc.get("taxes"):
		return
	template_doctype = INVOICE_DOCTYPES[doc.doctype]
	if not frappe.db.exists(template_doctype, doc.taxes_and_charges):
		return
	template = frappe.get_cached_doc(template_doctype, doc.taxes_and_charges)
	by_key = {(row.account_head, row.charge_type): row for row in template.taxes}
	fields = classification_fields(doc.doctype)
	for row in doc.taxes:
		source = by_key.get((row.account_head, row.charge_type))
		if not source:
			continue
		for field in fields:
			if not row.get(field) and source.get(field):
				row.set(field, source.get(field))


def check_classification(doc) -> None:
	purchase = doc.doctype == "Purchase Invoice"
	problems = []
	for row in doc.taxes:
		missing = []
		if row.es_tax_type in VAT_TYPES:
			if not row.es_vat_classification:
				missing.append(_("calificación o exención"))
			if not row.es_operation_type:
				missing.append(_("tipo de operación"))
			if purchase and not row.es_deductibility:
				missing.append(_("deducibilidad"))
		elif row.es_tax_type == TAX_TYPES["IRPF"]:
			if not row.es_withholding_key:
				missing.append(_("clave de retención"))
		elif not row.es_tax_type and is_tax_account(row.account_head):
			missing.append(_("tipo de impuesto"))
		if missing:
			problems.append(
				_("Fila {0} ({1}): falta {2}").format(row.idx, row.account_head, ", ".join(missing))
			)

	if problems:
		frappe.throw(
			_(
				"La compañía exige la clasificación fiscal de los impuestos y esta factura tiene"
				" filas sin clasificar:<br>{0}<br>Complete los campos en la tabla de impuestos o en la"
				" plantilla de impuestos de la factura."
			).format("<br>".join(problems)),
			title=_("Clasificación fiscal incompleta"),
		)


def is_tax_account(account: str | None) -> bool:
	return bool(account) and frappe.get_cached_value("Account", account, "account_type") == "Tax"
