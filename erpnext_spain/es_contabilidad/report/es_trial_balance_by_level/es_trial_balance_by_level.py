# Sumas y saldos PGC por niveles (spec 04 §4).
#
# Agrupa por prefijo del número de cuenta (1, 2, 3 o 4 dígitos, o cuenta), sin
# depender del árbol de ERPNext, que está partido por root_type: así se ve la
# estructura de grupos 1-9 del PGC.

import json

import frappe
from frappe import _
from frappe.query_builder import Case
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt

LEVELS = ("1", "2", "3", "4", "Cuenta")


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	for field in ("company", "from_date", "to_date"):
		if not filters.get(field):
			frappe.throw(_("Indique la compañía y el periodo."))
	frappe.has_permission("GL Entry", "read", throw=True)
	return columns(), data(filters)


def columns() -> list[dict]:
	currency = {"fieldtype": "Currency", "width": 140}
	return [
		{"fieldname": "account_number", "label": _("Cuenta"), "fieldtype": "Data", "width": 110},
		{"fieldname": "account_name", "label": _("Nombre"), "fieldtype": "Data", "width": 320},
		{"fieldname": "opening", "label": _("Saldo inicial"), **currency},
		{"fieldname": "debit", "label": _("Debe"), **currency},
		{"fieldname": "credit", "label": _("Haber"), **currency},
		{"fieldname": "closing", "label": _("Saldo final"), **currency},
	]


def balances(filters) -> list[dict]:
	gl = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	before = gl.posting_date < filters.from_date
	within = (gl.posting_date >= filters.from_date) & (gl.posting_date <= filters.to_date)
	query = (
		frappe.qb.from_(gl)
		.join(account)
		.on(account.name == gl.account)
		.select(
			account.account_number,
			account.account_name,
			Sum(Case().when(before, gl.debit - gl.credit).else_(0)).as_("opening"),
			Sum(Case().when(within, gl.debit).else_(0)).as_("debit"),
			Sum(Case().when(within, gl.credit).else_(0)).as_("credit"),
		)
		.where(gl.company == filters.company)
		.where(gl.is_cancelled == 0)
		.where(gl.posting_date <= filters.to_date)
		.where(account.account_number.isnotnull())
		.groupby(account.account_number, account.account_name)
	)
	if not cint(filters.get("include_closing")):
		query = query.where(gl.voucher_type != "Period Closing Voucher")
	if filters.get("finance_book"):
		query = query.where(
			(gl.finance_book == filters.finance_book) | gl.finance_book.isnull() | (gl.finance_book == "")
		)
	return query.run(as_dict=True)


def data(filters) -> list[dict]:
	level = filters.get("level") or "3"
	if level not in LEVELS:
		frappe.throw(_("Nivel no válido: elija 1, 2, 3, 4 o Cuenta."))
	names = group_names(filters.company)
	grouped: dict[str, dict] = {}
	for row in balances(filters):
		number = row.account_number.strip()
		key = number if level == "Cuenta" else number[: int(level)]
		entry = grouped.setdefault(
			key,
			{
				"account_number": key,
				"account_name": row.account_name if level == "Cuenta" else names.get(key, ""),
				"opening": 0.0,
				"debit": 0.0,
				"credit": 0.0,
			},
		)
		entry["opening"] += flt(row.opening)
		entry["debit"] += flt(row.debit)
		entry["credit"] += flt(row.credit)
	rows = []
	for key in sorted(grouped):
		entry = grouped[key]
		entry["closing"] = entry["opening"] + entry["debit"] - entry["credit"]
		if any(abs(entry[k]) > 0.005 for k in ("opening", "debit", "credit")):
			rows.append(entry)
	totals = {k: sum(r[k] for r in rows) for k in ("opening", "debit", "credit", "closing")}
	rows.append({"account_number": "", "account_name": _("Total"), **totals, "bold": 1})
	return rows


def group_names(company: str) -> dict[str, str]:
	"""Nombre de cada prefijo: grupos del BOE y cuentas numeradas de la compañía."""
	model = frappe.get_cached_value("Company", company, "es_chart_model")
	source = "boe_pgc_normal.json" if model == "Normal" else "boe_pgc_pymes.json"
	path = frappe.get_app_path("erpnext_spain", "es_contabilidad", "chart_of_accounts", "source", source)
	with open(path, encoding="utf-8") as f:
		data = json.load(f)
	names = {number: tidy(name) for number, name in data["accounts"]}
	names.update(data["groups"])
	for number, name in frappe.get_all(
		"Account",
		filters={"company": company, "account_number": ["is", "set"]},
		fields=["account_number", "account_name"],
		as_list=True,
	):
		names.setdefault(number, name)
	return names


def tidy(name: str) -> str:
	"""«CAPITAL» → «Capital»; quita el punto final del texto del BOE."""
	name = name.strip().rstrip(".")
	return name.capitalize() if name.isupper() else name
