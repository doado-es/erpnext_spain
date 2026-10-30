# Aplicación del plan PGC a una compañía (spec 02 §2-§3).

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe import _

from erpnext_spain.utils.gating import SPAIN

CHART_DIR = Path(__file__).resolve().parent / "chart_of_accounts"
CHART_FILES = {"Normal": "pgc_normal.json", "PYMES": "pgc_pymes.json"}
ALLOWED_ROLES = ("Accounts Manager", "System Manager")

# Longitud máxima de la abreviatura de la compañía con la que caben todos los
# nombres de cuenta del plan (chart_of_accounts/generate.py, MAX_COMPANY_ABBR).
MAX_COMPANY_ABBR = 12

# Doctypes por compañía que enlazan cuentas y que unset_existing_data de ERPNext
# no borra (verificado en v16.51: el asistente de configuración crea para
# España el Item Tax Template «Spain Tax», que bloquea el borrado de la cuenta
# de IVA). Se crean de nuevo después con los datos iniciales (spec 09 §3).
EXTRA_COMPANY_DOCTYPES = ("Tax Rule", "Item Tax Template")

# Cuentas por defecto de Company por número de cuenta (spec 02 §3, opción B e
# inventario administrativo A3). Propuesta pendiente de revisión contable.
DEFAULT_ACCOUNTS = {
	"default_receivable_account": "4300",
	"default_payable_account": "4000",
	"default_advance_received_account": "4380",
	"default_advance_paid_account": "4070",
	"default_cash_account": "5700",
	"default_bank_account": "5720",
	"default_income_account": "7000",
	"default_expense_account": "6000",
	# ERPNext usa una sola cuenta para diferencias positivas y negativas.
	"exchange_gain_loss_account": "6680",
	"unrealized_exchange_gain_loss_account": "6680",
	"round_off_account": "6590",
	"write_off_account": "6590",
	"accumulated_depreciation_account": "2819",
	"depreciation_expense_account": "6810",
	# ERPNext usa una sola cuenta para beneficios y pérdidas en la baja.
	"disposal_account": "6710",
	"asset_received_but_not_billed": "5230",
	"default_provisional_account": "4009",
	"default_deferred_revenue_account": "4850",
	"default_deferred_expense_account": "4800",
	"default_inventory_account": "3000",
	"stock_adjustment_account": "6100",
	# Sin inventario permanente el albarán de compra no genera asiento.
	"stock_received_but_not_billed": None,
}

# Funciones que crean los registros de compañía de la spec 09 §3 (plantillas
# de impuestos, reglas, cuentas de retención y de modos de pago). Se ejecutan
# después de crear el plan y fijar las cuentas por defecto. Cada spec añade la
# suya; reciben el nombre de la compañía y el modelo de plan.
COMPANY_SETUP_STEPS: list[str] = []


def load_chart(chart_model: str) -> dict:
	if chart_model not in CHART_FILES:
		frappe.throw(
			_("Modelo de plan «{0}» desconocido. Elija Normal o PYMES.").format(chart_model),
			title=_("Plan PGC"),
		)
	return json.loads((CHART_DIR / CHART_FILES[chart_model]).read_text(encoding="utf-8"))


def count_accounts(tree: dict) -> int:
	metadata = {"account_number", "account_type", "root_type", "is_group", "account_category"}
	total = 0
	for name, node in tree.items():
		if name in metadata:
			continue
		total += 1 + count_accounts(node)
	return total


@frappe.whitelist(methods=["POST"])
def apply_pgc_chart(company: str, chart_model: str, dry_run: bool = True) -> dict:
	"""Sustituye el plan de cuentas de una compañía sin movimientos por el plan PGC.

	Con ``dry_run`` (por defecto) solo devuelve el resumen de lo que haría."""
	check_permissions(company)
	validate_preconditions(company)
	chart = load_chart(chart_model)

	summary = build_summary(company, chart_model, chart)
	if dry_run:
		return summary

	clear_company_chart(company)

	from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import create_charts

	create_charts(company, custom_chart=chart["tree"])
	set_company_defaults(company, chart_model)

	for step in COMPANY_SETUP_STEPS:
		frappe.get_attr(step)(company, chart_model)

	from erpnext.accounts.doctype.financial_report_template.financial_report_template import (
		sync_financial_report_templates,
	)

	sync_financial_report_templates()

	frappe.get_doc("Company", company).add_comment(
		"Info",
		_("Plan {0} aplicado (versión {1} de los datos del plan; BOE actualizado a {2}).").format(
			chart["name"], chart["version"], chart.get("boe_last_update") or "-"
		),
	)
	summary["applied"] = True
	return summary


def check_permissions(company: str) -> None:
	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Solo un usuario con rol {0} puede aplicar el plan PGC.").format(
				_(" o ").join(_(role) for role in ALLOWED_ROLES)
			),
			frappe.PermissionError,
		)
	if not frappe.has_permission("Company", "write", doc=company):
		frappe.throw(
			_("No tiene permiso de escritura sobre la compañía {0}.").format(frappe.bold(company)),
			frappe.PermissionError,
		)


def validate_preconditions(company: str) -> None:
	values = frappe.db.get_value(
		"Company",
		company,
		[
			"country",
			"abbr",
			"es_pgc_applied",
			"parent_company",
			"allow_account_creation_against_child_company",
		],
		as_dict=True,
	)
	if not values:
		frappe.throw(_("La compañía {0} no existe.").format(frappe.bold(company)), frappe.DoesNotExistError)
	if values.country != SPAIN:
		frappe.throw(
			_(
				"El plan PGC solo se aplica a compañías de España; {0} es de {1}. Cambie el país de la"
				" compañía si es un error."
			).format(frappe.bold(company), values.country or "-"),
			title=_("Plan PGC"),
		)
	if values.es_pgc_applied:
		frappe.throw(
			_("La compañía {0} ya tiene el plan PGC aplicado.").format(frappe.bold(company)),
			title=_("Plan PGC"),
		)
	if frappe.db.exists("GL Entry", {"company": company}):
		frappe.throw(
			_(
				"La compañía {0} ya tiene movimientos contables: el plan PGC solo se aplica a compañías"
				" sin movimientos. Cree una compañía nueva o adapte el plan actual a mano."
			).format(frappe.bold(company)),
			title=_("Plan PGC"),
		)
	if values.parent_company and not values.allow_account_creation_against_child_company:
		frappe.throw(
			_(
				"{0} es una compañía dependiente de {1} y su plan de cuentas viene de la matriz. Aplique"
				" el plan PGC a la matriz o active «Allow Account Creation Against Child Company»."
			).format(frappe.bold(company), frappe.bold(values.parent_company)),
			title=_("Plan PGC"),
		)
	if len(values.abbr or "") > MAX_COMPANY_ABBR:
		frappe.throw(
			_(
				"La abreviatura de la compañía ({0}) tiene más de {1} caracteres y algunos nombres de"
				" cuenta del PGC no cabrían. Acórtela y vuelva a intentarlo."
			).format(values.abbr, MAX_COMPANY_ABBR),
			title=_("Plan PGC"),
		)


def build_summary(company: str, chart_model: str, chart: dict) -> dict:
	extra = {
		doctype: frappe.db.count(doctype, {"company": company})
		for doctype in (
			*EXTRA_COMPANY_DOCTYPES,
			"Sales Taxes and Charges Template",
			"Purchase Taxes and Charges Template",
		)
	}
	return {
		"company": company,
		"chart_model": chart_model,
		"chart": chart["name"],
		"version": chart["version"],
		"accounts_to_delete": frappe.db.count("Account", {"company": company}),
		"accounts_to_create": count_accounts(chart["tree"]),
		"records_to_delete": {doctype: count for doctype, count in extra.items() if count},
		"default_accounts": {field: number for field, number in DEFAULT_ACCOUNTS.items() if number},
		"perpetual_inventory": 0,
		"applied": False,
	}


def clear_company_chart(company: str) -> None:
	"""Borra el plan de cuentas de una compañía sin movimientos y lo que lo enlaza.

	Usa unset_existing_data del importador de planes de ERPNext (vacía las
	cuentas por defecto de Company y borra cuentas, cuentas de terceros, de modos
	de pago, de retención y plantillas de impuestos de venta y compra), después
	de borrar lo que esa función no contempla."""
	from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
		unset_existing_data,
	)

	for doctype in EXTRA_COMPANY_DOCTYPES:
		for name in frappe.get_all(doctype, filters={"company": company}, pluck="name"):
			frappe.delete_doc(doctype, name, ignore_permissions=True)
	unset_existing_data(company)


def account_by_number(company: str, number: str) -> str:
	account = frappe.db.get_value("Account", {"company": company, "account_number": number}, "name")
	if not account:
		frappe.throw(_("No se encuentra la cuenta {0} en el plan aplicado.").format(number))
	return account


def set_company_defaults(company: str, chart_model: str) -> None:
	"""Fija explícitamente las cuentas por defecto (no se usa set_default_accounts
	del importador: tomaría la primera cuenta Receivable, que podría ser la 438, y
	crearía la plantilla de IVA genérica), desactiva el inventario permanente
	(A3) y marca la compañía. Se guarda con doc.save() para que ERPNext valide
	las cuentas (tipo, rama, moneda)."""
	doc = frappe.get_doc("Company", company)
	for field, number in DEFAULT_ACCOUNTS.items():
		doc.set(field, account_by_number(company, number) if number else None)
	doc.enable_perpetual_inventory = 0
	doc.es_pgc_applied = 1
	doc.es_chart_model = chart_model
	doc.flags.ignore_permissions = True
	doc.save()
