# Filas de los estados PGC que dependen del signo del saldo (spec 04 §3).
#
# Las cuentas que el modelo oficial presenta en el activo o en el pasivo según
# su saldo (p. ej. 551, 5523-5525) se suman en la fila del lado que pide la
# fila: «deudor» solo con saldo deudor, «acreedor» solo con saldo acreedor. El
# resto de cuentas de la fila se suma siempre.
#
# Los saldos se calculan con la misma clase que usa el motor de plantillas de
# ERPNext (FinancialQueryBuilder), llamándola sin modificarla: saldo inicial,
# asientos de cierre y filtros del informe se tratan igual que en las filas
# «Account Data». Es API interna de ERPNext: la cubren los tests.
#
# En las cuentas de clientes y proveedores (tipo Receivable/Payable) el signo
# se mira por tercero: un cliente con saldo acreedor va al pasivo aunque la
# 4300 en conjunto sea deudora (spec 04 §3, criterio 4). Ese saldo por tercero
# se calcula sobre GL Entry con los mismos filtros estándar del motor.

PARTY_ACCOUNT_TYPES = ("Receivable", "Payable")

from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_spain.es_contabilidad.statements.mapping import find_row, prefixes

SIDES = ("deudor", "acreedor")


@frappe.whitelist(methods=["GET"])
def balance_by_sign(filters: dict, periods: list, row: Document | dict) -> list[float]:
	"""Valores por periodo de una fila «signo» de una plantilla PGC, en el signo
	del motor (debe - haber); el motor aplica después reverse_sign."""
	frappe.has_permission("GL Entry", "read", throw=True)
	row = frappe._dict(row.as_dict() if isinstance(row, Document) else row)
	config = find_row(row.parent, row.reference_code)
	if not config or config["lado"] not in SIDES:
		frappe.throw(
			_("La fila {0} de la plantilla {1} no tiene configuración de signo en el mapeo PGC.").format(
				row.reference_code, row.parent
			)
		)

	accounts = matching_accounts(filters.get("company"), prefixes(config["incluir"]))
	if not accounts:
		return [0.0] * len(periods)

	from erpnext.accounts.doctype.financial_report_template.financial_report_engine import (
		FinancialQueryBuilder,
	)

	builder = FinancialQueryBuilder(filters, periods)
	balances = builder.fetch_account_balances(accounts)
	period_keys = [period["key"] for period in periods]
	by_sign = prefixes(config["segun_signo"])
	debit_side = config["lado"] == "deudor"
	balance_type = row.balance_type or "Closing Balance"
	party_accounts = [
		a
		for a in accounts
		if a.account_type in PARTY_ACCOUNT_TYPES
		and balance_type == "Closing Balance"
		and any(a.account_number.startswith(prefix) for prefix in by_sign)
	]
	by_party = party_balances(builder, party_accounts, periods) if party_accounts else {}
	totals = [0.0] * len(periods)
	for account in accounts:
		signed = any(account.account_number.startswith(prefix) for prefix in by_sign)
		if account.name in by_party:
			for values in by_party[account.name]:
				for i, value in enumerate(values):
					if not (value <= 0 if debit_side else value >= 0):
						totals[i] += value
			continue
		data = balances.get(account.name)
		if not data:
			continue
		for i, value in enumerate(data.get_ordered_values(period_keys, balance_type)):
			if signed and (value <= 0 if debit_side else value >= 0):
				continue
			totals[i] += value
	return totals


def party_balances(builder, accounts: list, periods: list) -> dict[str, list[list[float]]]:
	"""Saldo de cierre por cuenta y tercero en cada periodo (debe - haber)."""
	from frappe.query_builder import Case
	from frappe.query_builder.functions import Sum

	gl = frappe.qb.DocType("GL Entry")
	query = (
		frappe.qb.from_(gl)
		.select(gl.account, gl.party)
		.where(gl.company == builder.filters.get("company"))
		.where(gl.is_cancelled == 0)
		.where(gl.account.isin([a.name for a in accounts]))
		.groupby(gl.account, gl.party)
	)
	for period in periods:
		query = query.select(
			Sum(Case().when(gl.posting_date <= period["to_date"], gl.debit - gl.credit).else_(0)).as_(
				period["key"]
			)
		)
	# Mismos filtros que las filas «Account Data» (cierre, libro, dimensiones).
	query = builder._apply_standard_filters(query, gl)
	result: dict[str, list[list[float]]] = {}
	for line in query.run(as_dict=True):
		result.setdefault(line.account, []).append([float(line.get(p["key"]) or 0) for p in periods])
	return result


def matching_accounts(company: str | None, include: list[str]) -> list[Any]:
	if not company or not include:
		return []
	account = frappe.qb.DocType("Account")
	condition = None
	for prefix in include:
		like = account.account_number.like(f"{prefix}%")
		condition = like if condition is None else condition | like
	return (
		frappe.qb.from_(account)
		.select(account.name, account.account_name, account.account_number, account.account_type)
		.where(account.company == company)
		.where(account.is_group == 0)
		.where(account.disabled == 0)
		.where(condition)
		.orderby(account.name)
		.run(as_dict=True)
	)
