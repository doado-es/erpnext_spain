# Libros registro de IVA y borrador de liquidación (spec 06 §5).
#
# Leen el Registro Fiscal IVA (sin filas anuladas). Los libros excluyen las
# retenciones; el borrador de liquidación NO es el modelo 303.

import frappe
from frappe import _
from frappe.query_builder.functions import Sum

from erpnext_spain.es_impuestos.codes import TAX_TYPES

REGISTER = "ES Vat Register"
VAT_TYPES = (TAX_TYPES["IVA"], TAX_TYPES["RE"])


def check_filters(filters) -> frappe._dict:
	filters = frappe._dict(filters or {})
	for field in ("company", "from_date", "to_date"):
		if not filters.get(field):
			frappe.throw(_("Indique la compañía y el periodo."))
	return filters


def book_rows(filters, book: str) -> list[dict]:
	register = frappe.qb.DocType(REGISTER)
	query = (
		frappe.qb.from_(register)
		.select(
			register.posting_date,
			register.issue_date,
			register.voucher_type,
			register.voucher_no,
			register.invoice_type,
			register.supplier_invoice_no,
			register.rectified_invoice,
			register.party,
			register.party_name,
			register.tax_id,
			register.country,
			register.tax_type,
			register.vat_classification,
			register.operation_type,
			register.deductibility,
			register.taxable_base,
			register.tax_rate,
			register.tax_amount,
			register.deductible_amount,
			register.self_assessed,
			register.unclassified,
		)
		.where(register.company == filters.company)
		.where(register.book == book)
		.where(register.cancelled == 0)
		.where(register.tax_type.isin(VAT_TYPES))
		.where(register.posting_date[filters.from_date : filters.to_date])
		.orderby(register.posting_date)
		.orderby(register.voucher_no)
	)
	return query.run(as_dict=True)


def book_columns(received: bool) -> list[dict]:
	columns = [
		{"fieldname": "posting_date", "label": _("Fecha"), "fieldtype": "Date", "width": 95},
		{"fieldname": "voucher_type", "label": _("Tipo de documento"), "fieldtype": "Data", "hidden": 1},
		{
			"fieldname": "voucher_no",
			"label": _("Factura"),
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 160,
		},
	]
	if received:
		columns += [
			{
				"fieldname": "supplier_invoice_no",
				"label": _("Número del proveedor"),
				"fieldtype": "Data",
				"width": 130,
			},
			{"fieldname": "issue_date", "label": _("Fecha de expedición"), "fieldtype": "Date", "width": 95},
		]
	columns += [
		{"fieldname": "invoice_type", "label": _("Tipo"), "fieldtype": "Data", "width": 50},
		{"fieldname": "rectified_invoice", "label": _("Rectifica a"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "party_name",
			"label": _("Proveedor") if received else _("Cliente"),
			"fieldtype": "Data",
			"width": 180,
		},
		{"fieldname": "tax_id", "label": _("NIF"), "fieldtype": "Data", "width": 110},
		{"fieldname": "tax_type", "label": _("Impuesto"), "fieldtype": "Data", "width": 110},
		{"fieldname": "vat_classification", "label": _("Calificación"), "fieldtype": "Data", "width": 60},
		{"fieldname": "operation_type", "label": _("Tipo de operación"), "fieldtype": "Data", "width": 150},
		{"fieldname": "taxable_base", "label": _("Base imponible"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "tax_rate", "label": _("Tipo (%)"), "fieldtype": "Percent", "width": 70},
		{"fieldname": "tax_amount", "label": _("Cuota"), "fieldtype": "Currency", "width": 110},
	]
	if received:
		columns += [
			{
				"fieldname": "deductible_amount",
				"label": _("Cuota deducible"),
				"fieldtype": "Currency",
				"width": 110,
			},
			{"fieldname": "self_assessed", "label": _("Autorrepercutida"), "fieldtype": "Check", "width": 80},
		]
	columns.append(
		{"fieldname": "unclassified", "label": _("Sin clasificar"), "fieldtype": "Check", "width": 80}
	)
	return columns


def return_draft(filters) -> list[dict]:
	"""IVA devengado (expedidas + autorrepercutidas), IVA deducible y resultado."""
	register = frappe.qb.DocType(REGISTER)
	base = (
		frappe.qb.from_(register)
		.where(register.company == filters.company)
		.where(register.cancelled == 0)
		.where(register.tax_type.isin(VAT_TYPES))
		.where(register.posting_date[filters.from_date : filters.to_date])
	)
	accrued = (
		base.select(
			register.tax_type,
			register.tax_rate,
			register.self_assessed,
			Sum(register.taxable_base).as_("taxable_base"),
			Sum(register.tax_amount).as_("tax_amount"),
		)
		.where((register.book == "Expedidas") | (register.self_assessed == 1))
		.groupby(register.self_assessed, register.tax_type, register.tax_rate)
		.orderby(register.self_assessed)
		.orderby(register.tax_type)
		.orderby(register.tax_rate)
	).run(as_dict=True)
	deductible = (
		base.select(
			register.deductibility,
			Sum(register.taxable_base).as_("taxable_base"),
			Sum(register.deductible_amount).as_("tax_amount"),
		)
		.where(register.book == "Recibidas")
		.where(register.self_assessed == 0)
		.groupby(register.deductibility)
	).run(as_dict=True)

	rows = [{"concept": _("IVA devengado"), "indent": 0, "bold": 1}]
	total_accrued = 0.0
	for row in accrued:
		label = _("Autorrepercutido") if row.self_assessed else _("Régimen general")
		rows.append(
			{
				"concept": f"{label} · {_(row.tax_type)} {row.tax_rate:g} %",
				"indent": 1,
				"taxable_base": row.taxable_base,
				"tax_amount": row.tax_amount,
			}
		)
		total_accrued += row.tax_amount or 0
	rows.append({"concept": _("Total devengado"), "indent": 0, "tax_amount": total_accrued, "bold": 1})
	rows.append({"concept": _("IVA deducible"), "indent": 0, "bold": 1})
	total_deductible = 0.0
	for row in deductible:
		rows.append(
			{
				"concept": _(row.deductibility or "Sin indicar"),
				"indent": 1,
				"taxable_base": row.taxable_base,
				"tax_amount": row.tax_amount,
			}
		)
		total_deductible += row.tax_amount or 0
	rows.append({"concept": _("Total deducible"), "indent": 0, "tax_amount": total_deductible, "bold": 1})
	rows.append(
		{
			"concept": _("Resultado (borrador, no es el modelo 303)"),
			"indent": 0,
			"tax_amount": total_accrued - total_deductible,
			"bold": 1,
		}
	)
	return rows
