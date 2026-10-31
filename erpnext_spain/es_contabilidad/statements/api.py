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

	balances = FinancialQueryBuilder(filters, periods).fetch_account_balances(accounts)
	period_keys = [period["key"] for period in periods]
	by_sign = prefixes(config["segun_signo"])
	debit_side = config["lado"] == "deudor"
	totals = [0.0] * len(periods)
	for account in accounts:
		data = balances.get(account.name)
		if not data:
			continue
		signed = any(account.account_number.startswith(prefix) for prefix in by_sign)
		for i, value in enumerate(
			data.get_ordered_values(period_keys, row.balance_type or "Closing Balance")
		):
			if signed and (value <= 0 if debit_side else value >= 0):
				continue
			totals[i] += value
	return totals


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
		.select(account.name, account.account_name, account.account_number)
		.where(account.company == company)
		.where(account.is_group == 0)
		.where(account.disabled == 0)
		.where(condition)
		.orderby(account.name)
		.run(as_dict=True)
	)
