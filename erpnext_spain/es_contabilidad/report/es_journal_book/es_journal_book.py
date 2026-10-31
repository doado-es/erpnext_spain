# Libro diario PGC (spec 04 §5).
#
# Número de asiento correlativo por ejercicio y compañía. Un asiento es un
# comprobante (voucher_type + voucher_no). Orden: apertura, ordinarios y
# regularización (Period Closing Voucher; ERPNext no tiene asiento de cierre
# de las cuentas de balance, se reabren con el de apertura del ejercicio siguiente); dentro de cada clase, por
# fecha, tipo y número de comprobante. El orden es determinista, así que la
# numeración es estable entre ejecuciones mientras no se añadan asientos con
# fecha anterior (al legalizar el libro se numera el ejercicio cerrado).

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import getdate

OPENING, ORDINARY, REGULARISATION = "Apertura", "Ordinario", "Regularización"
ORDER = {OPENING: 0, ORDINARY: 1, REGULARISATION: 2}


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	if not filters.get("company") or not filters.get("fiscal_year"):
		frappe.throw(_("Indique la compañía y el ejercicio."))
	frappe.has_permission("GL Entry", "read", throw=True)
	return columns(), data(filters)


def columns() -> list[dict]:
	return [
		{"fieldname": "entry_no", "label": _("Asiento"), "fieldtype": "Int", "width": 80},
		{"fieldname": "posting_date", "label": _("Fecha"), "fieldtype": "Date", "width": 95},
		{"fieldname": "entry_class", "label": _("Clase"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "account",
			"label": _("Cuenta"),
			"fieldtype": "Link",
			"options": "Account",
			"width": 260,
		},
		{"fieldname": "remarks", "label": _("Concepto"), "fieldtype": "Data", "width": 260},
		{"fieldname": "debit", "label": _("Debe"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "credit", "label": _("Haber"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "voucher_type", "label": _("Tipo de documento"), "fieldtype": "Data", "width": 140},
		{
			"fieldname": "voucher_no",
			"label": _("Documento"),
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 160,
		},
	]


def entry_class(row) -> str:
	if row.voucher_type == "Period Closing Voucher":
		return REGULARISATION
	if row.is_opening == "Yes" or row.je_type == "Opening Entry":
		return OPENING
	return ORDINARY


def gl_lines(company: str, start, end) -> list[dict]:
	gl = frappe.qb.DocType("GL Entry")
	je = frappe.qb.DocType("Journal Entry")
	return (
		frappe.qb.from_(gl)
		.left_join(je)
		.on((gl.voucher_type == "Journal Entry") & (je.name == gl.voucher_no))
		.select(
			gl.posting_date,
			gl.voucher_type,
			gl.voucher_no,
			gl.account,
			gl.is_opening,
			je.voucher_type.as_("je_type"),
			gl.remarks,
			Sum(gl.debit).as_("debit"),
			Sum(gl.credit).as_("credit"),
		)
		.where(gl.company == company)
		.where(gl.is_cancelled == 0)
		.where(gl.posting_date[start:end])
		.groupby(
			gl.posting_date,
			gl.voucher_type,
			gl.voucher_no,
			gl.account,
			gl.is_opening,
			je.voucher_type,
			gl.remarks,
		)
	).run(as_dict=True)


def numbered_lines(company: str, fiscal_year: str) -> list[dict]:
	start, end = frappe.get_cached_value("Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"])
	lines = gl_lines(company, start, end)
	vouchers: dict[tuple, dict] = {}
	for line in lines:
		key = (line.voucher_type, line.voucher_no)
		info = vouchers.setdefault(key, {"date": line.posting_date, "class": entry_class(line)})
		info["date"] = min(info["date"], line.posting_date)
	order = sorted(
		vouchers, key=lambda k: (ORDER[vouchers[k]["class"]], getdate(vouchers[k]["date"]), k[0], k[1])
	)
	numbers = {key: i + 1 for i, key in enumerate(order)}
	for line in lines:
		key = (line.voucher_type, line.voucher_no)
		line.entry_no = numbers[key]
		line.entry_class = vouchers[key]["class"]
	lines.sort(key=lambda r: (r.entry_no, -(r.debit or 0), r.account))
	return lines


def data(filters) -> list[dict]:
	lines = numbered_lines(filters.company, filters.fiscal_year)
	if filters.get("from_date"):
		lines = [r for r in lines if getdate(r.posting_date) >= getdate(filters.from_date)]
	if filters.get("to_date"):
		lines = [r for r in lines if getdate(r.posting_date) <= getdate(filters.to_date)]
	previous = None
	for line in lines:
		if line.entry_no == previous:
			line.entry_no = None  # el número solo en la primera línea del asiento
			line.posting_date = None
			line.entry_class = None
		else:
			previous = line.entry_no
	totals = {"debit": sum(r.debit or 0 for r in lines), "credit": sum(r.credit or 0 for r in lines)}
	return [*lines, {"remarks": _("Total"), **totals, "bold": 1}]
