# Libros registro de IVA y borrador de liquidación (spec 06 §5).
#
# Calculan el desglose de las facturas validadas del periodo (es_iva/rows.py);
# las canceladas no cuentan. Los libros excluyen las retenciones; el borrador de
# liquidación NO es el modelo 303.

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_spain.es_iva.rows import period_rows


def check_filters(filters) -> frappe._dict:
	filters = frappe._dict(filters or {})
	for field in ("company", "from_date", "to_date"):
		if not filters.get(field):
			frappe.throw(_("Indique la compañía y el periodo."))
	return filters


def book_rows(filters, book: str) -> list[dict]:
	return period_rows(filters.company, filters.from_date, filters.to_date, book=book)


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
	rows = period_rows(filters.company, filters.from_date, filters.to_date)
	accrued: dict[tuple, dict] = {}
	deductible: dict[str, dict] = {}
	for row in rows:
		if row.book == "Expedidas" or row.self_assessed:
			key = (row.self_assessed, row.tax_type, row.tax_rate)
			group = accrued.setdefault(key, {"taxable_base": 0.0, "tax_amount": 0.0})
			group["taxable_base"] += flt(row.taxable_base)
			group["tax_amount"] += flt(row.tax_amount)
		else:
			group = deductible.setdefault(row.deductibility or "", {"taxable_base": 0.0, "tax_amount": 0.0})
			group["taxable_base"] += flt(row.taxable_base)
			group["tax_amount"] += flt(row.deductible_amount)

	result = [{"concept": _("IVA devengado"), "indent": 0, "bold": 1}]
	total_accrued = 0.0
	for (self_assessed, tax_type, rate), values in sorted(accrued.items()):
		label = _("Autorrepercutido") if self_assessed else _("Régimen general")
		result.append({"concept": f"{label} · {_(tax_type)} {rate:g} %", "indent": 1, **values})
		total_accrued += values["tax_amount"]
	result.append({"concept": _("Total devengado"), "indent": 0, "tax_amount": total_accrued, "bold": 1})
	result.append({"concept": _("IVA deducible"), "indent": 0, "bold": 1})
	total_deductible = 0.0
	for deductibility, values in sorted(deductible.items()):
		result.append({"concept": _(deductibility or "Sin indicar"), "indent": 1, **values})
		total_deductible += values["tax_amount"]
	result.append({"concept": _("Total deducible"), "indent": 0, "tax_amount": total_deductible, "bold": 1})
	result.append(
		{
			"concept": _("Resultado (borrador, no es el modelo 303)"),
			"indent": 0,
			"tax_amount": total_accrued - total_deductible,
			"bold": 1,
		}
	)
	return result
