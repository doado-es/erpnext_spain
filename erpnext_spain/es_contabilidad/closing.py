# Asientos de cierre propios del PGC (spec 04 §6 y §7).
#
# Los dos generan un Journal Entry nativo en BORRADOR (con las dimensiones por
# defecto de la compañía, R9) para que el usuario lo revise y lo valide:
#
# - Traspaso de los grupos 8 y 9 (gastos e ingresos imputados al patrimonio
#   neto) a sus cuentas del subgrupo 13 (y 115). El Period Closing Voucher de
#   ERPNext solo cierra los grupos 6 y 7.
# - Regularización de existencias (inventario administrativo, decisión A3): baja
#   de la existencia inicial (61x/71x a 30x) y alta de la final (30x a 61x/71x),
#   valorada con el Stock Ledger a la fecha de cierre. Va antes del Period
#   Closing Voucher.
#
# Tablas de correspondencias **[revisar con un contable]**.

import frappe
from frappe import _
from frappe.query_builder.functions import Max, Sum
from frappe.utils import cint, flt, getdate

from erpnext_spain.utils.gating import is_pgc_company

TRANSFER_89 = "Traspaso de los grupos 8 y 9"
INVENTORY = "Regularización de existencias"
CLOSING_TYPES = (TRANSFER_89, INVENTORY)
ALLOWED_ROLES = ("Accounts Manager", "System Manager")

# Prefijo de cuenta de los grupos 8/9 → cuenta de destino (gana el más largo).
GROUP_89_TARGETS = (
	("80", "1330"),
	("90", "1330"),
	("89", "1330"),
	("99", "1330"),
	("81", "1340"),
	("91", "1340"),
	("812", "1341"),
	("813", "1341"),
	("912", "1341"),
	("913", "1341"),
	("82", "1350"),
	("92", "1350"),
	("83", "1330"),
	("838", "1360"),
	("84", "1300"),
	("841", "1310"),
	("842", "1320"),
	("94", "1300"),
	("941", "1310"),
	("942", "1320"),
	("85", "1150"),
	("95", "1150"),
	("86", "1360"),
	("96", "1360"),
)

# Clase de existencias del grupo de artículos → (existencias, variación).
INVENTORY_CLASSES = {
	"Mercaderías": ("300", "610"),
	"Materias primas": ("310", "611"),
	"Otros aprovisionamientos": ("320", "612"),
	"Productos en curso": ("330", "710"),
	"Productos semiterminados": ("340", "711"),
	"Productos terminados": ("350", "712"),
	"Subproductos, residuos y materiales recuperados": ("360", "713"),
}
DEFAULT_INVENTORY_CLASS = "Mercaderías"


# --- comunes -----------------------------------------------------------------------


def check_access(company: str) -> None:
	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Solo un usuario con rol Accounts Manager puede generar asientos de cierre."),
			frappe.PermissionError,
		)
	frappe.get_doc("Company", company).check_permission("write")
	if not is_pgc_company(company):
		frappe.throw(_("La compañía {0} no tiene el plan PGC aplicado.").format(frappe.bold(company)))


def check_not_done(company: str, closing_type: str, posting_date) -> None:
	existing = frappe.get_all(
		"Journal Entry",
		filters={
			"company": company,
			"es_closing_type": closing_type,
			"posting_date": posting_date,
			"docstatus": ["<", 2],
		},
		pluck="name",
	)
	if existing:
		frappe.throw(
			_(
				"Ya existe el asiento {0} de {1} con fecha {2}. Anúlelo o bórrelo antes de generar otro."
			).format(frappe.bold(existing[0]), _(closing_type), frappe.utils.formatdate(posting_date)),
			title=_("Asiento ya generado"),
		)


def leaf(company: str, number: str) -> str:
	"""Cuenta hoja de la compañía con ese número o, si es un grupo, su primera hoja."""
	for value, condition in ((number, "="), (f"{number}%", "like")):
		name = frappe.db.get_value(
			"Account",
			{"company": company, "account_number": [condition, value], "is_group": 0},
			"name",
			order_by="account_number",
		)
		if name:
			return name
	frappe.throw(
		_("Falta la cuenta {0} en la compañía {1}. Créela en el plan de cuentas.").format(
			frappe.bold(number), frappe.bold(company)
		)
	)


def draft_entry(company: str, posting_date, closing_type: str, remark: str, lines: list[dict]) -> str:
	cost_center = frappe.get_cached_value("Company", company, "cost_center")
	entry = frappe.new_doc("Journal Entry")
	entry.update(
		{
			"voucher_type": "Journal Entry",
			"company": company,
			"posting_date": posting_date,
			"user_remark": remark,
			"es_closing_type": closing_type,
		}
	)
	for line in lines:
		entry.append("accounts", {"cost_center": cost_center, **line})
	entry.insert()
	return entry.name


def pair(debit_account: str, credit_account: str, amount: float) -> list[dict]:
	"""Cargo y abono por el importe; si es negativo, se invierten."""
	amount = flt(amount, 2)
	if not amount:
		return []
	if amount < 0:
		debit_account, credit_account, amount = credit_account, debit_account, -amount
	return [
		{"account": debit_account, "debit_in_account_currency": amount},
		{"account": credit_account, "credit_in_account_currency": amount},
	]


def balance_lines(amounts: dict[str, float]) -> list[dict]:
	lines = []
	for account, amount in amounts.items():
		amount = flt(amount, 2)
		if amount > 0:
			lines.append({"account": account, "debit_in_account_currency": amount})
		elif amount < 0:
			lines.append({"account": account, "credit_in_account_currency": -amount})
	return lines


# --- traspaso de los grupos 8 y 9 --------------------------------------------------


def target_for(number: str) -> str | None:
	match = None
	for prefix, target in GROUP_89_TARGETS:
		if number.startswith(prefix) and (match is None or len(prefix) > len(match[0])):
			match = (prefix, target)
	return match[1] if match else None


def group_89_balances(company: str, posting_date) -> list[dict]:
	start = frappe.db.get_value(
		"Fiscal Year",
		{"year_start_date": ["<=", posting_date], "year_end_date": [">=", posting_date], "disabled": 0},
		"year_start_date",
	)
	gl = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	query = (
		frappe.qb.from_(gl)
		.join(account)
		.on(account.name == gl.account)
		.select(gl.account, account.account_number, Sum(gl.debit - gl.credit).as_("balance"))
		.where(gl.company == company)
		.where(gl.is_cancelled == 0)
		.where(gl.posting_date <= posting_date)
		.where(account.account_number.like("8%") | account.account_number.like("9%"))
		.groupby(gl.account, account.account_number)
	)
	if start:
		query = query.where(gl.posting_date >= start)
	return [row for row in query.run(as_dict=True) if abs(flt(row.balance)) > 0.005]


@frappe.whitelist(methods=["POST"])
def transfer_groups_8_9(company: str, posting_date: str, dry_run: bool = True) -> dict:
	"""Traspasa al patrimonio neto los saldos del ejercicio de los grupos 8 y 9."""
	check_access(company)
	posting_date = getdate(posting_date)
	check_not_done(company, TRANSFER_89, posting_date)
	amounts: dict[str, float] = {}
	summary = []
	for row in group_89_balances(company, posting_date):
		target_number = target_for(row.account_number)
		if not target_number:
			frappe.throw(
				_("La cuenta {0} no tiene cuenta de destino en el traspaso de los grupos 8 y 9.").format(
					row.account
				)
			)
		target = leaf(company, target_number)
		amounts[row.account] = amounts.get(row.account, 0) - flt(row.balance)
		amounts[target] = amounts.get(target, 0) + flt(row.balance)
		summary.append({"account": row.account, "balance": flt(row.balance), "target": target})
	if not summary:
		frappe.throw(
			_("No hay saldos en los grupos 8 y 9 en el ejercicio de {0}.").format(
				frappe.utils.formatdate(posting_date)
			)
		)
	result = {"lines": summary}
	if not cint(dry_run):
		result["journal_entry"] = draft_entry(
			company,
			posting_date,
			TRANSFER_89,
			_("Traspaso de los grupos 8 y 9 al patrimonio neto"),
			balance_lines(amounts),
		)
	return result


# --- regularización de existencias ---------------------------------------------------


def inventory_class(item_group: str | None) -> str:
	value = frappe.get_cached_value("Item Group", item_group, "es_inventory_class") if item_group else None
	return value if value in INVENTORY_CLASSES else DEFAULT_INVENTORY_CLASS


def stock_values(company: str, posting_date) -> dict[str, float]:
	"""Valor del Stock Ledger por clase de existencias a la fecha (último
	movimiento de cada artículo y almacén)."""
	sle = frappe.qb.DocType("Stock Ledger Entry")
	latest = (
		frappe.qb.from_(sle)
		.select(sle.item_code, sle.warehouse, Max(sle.posting_datetime).as_("at"))
		.where(sle.company == company)
		.where(sle.is_cancelled == 0)
		.where(sle.posting_date <= posting_date)
		.groupby(sle.item_code, sle.warehouse)
	).run(as_dict=True)
	values: dict[str, float] = {}
	for row in latest:
		value = frappe.get_all(
			"Stock Ledger Entry",
			filters={
				"item_code": row.item_code,
				"warehouse": row.warehouse,
				"posting_datetime": row.at,
				"is_cancelled": 0,
			},
			fields=["stock_value"],
			order_by="creation desc",
			limit=1,
		)
		group = frappe.get_cached_value("Item", row.item_code, "item_group")
		key = inventory_class(group)
		values[key] = values.get(key, 0) + flt(value[0].stock_value if value else 0)
	return values


def account_balance(company: str, prefix: str, posting_date) -> dict[str, float]:
	gl = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	rows = (
		frappe.qb.from_(gl)
		.join(account)
		.on(account.name == gl.account)
		.select(gl.account, Sum(gl.debit - gl.credit).as_("balance"))
		.where(gl.company == company)
		.where(gl.is_cancelled == 0)
		.where(gl.posting_date <= posting_date)
		.where(account.account_number.like(f"{prefix}%"))
		.groupby(gl.account)
	).run(as_dict=True)
	return {row.account: flt(row.balance) for row in rows if abs(flt(row.balance)) > 0.005}


@frappe.whitelist(methods=["POST"])
def regularise_inventory(
	company: str, posting_date: str, final_values: dict | None = None, dry_run: bool = True
) -> dict:
	"""Propone (dry_run) o crea en borrador el asiento de regularización.

	`final_values` permite corregir la existencia final por clase (p. ej. tras
	un recuento): {"Mercaderías": 1500}."""
	check_access(company)
	posting_date = getdate(posting_date)
	check_not_done(company, INVENTORY, posting_date)
	if isinstance(final_values, str):
		final_values = frappe.parse_json(final_values)
	valued = stock_values(company, posting_date)
	valued.update({k: flt(v) for k, v in (final_values or {}).items() if k in INVENTORY_CLASSES})

	summary = []
	lines: list[dict] = []
	for name, (stock_prefix, variation_prefix) in INVENTORY_CLASSES.items():
		initial = account_balance(company, stock_prefix, posting_date)
		final = flt(valued.get(name))
		if not initial and not final:
			continue
		variation = leaf(company, variation_prefix)
		stock_account = next(iter(initial), None) or leaf(company, stock_prefix)
		# Se asientan las dos partidas (baja de la inicial y alta de la final) por
		# claridad en el libro diario.
		for account, balance in initial.items():
			lines += pair(variation, account, balance)
		lines += pair(stock_account, variation, final)
		summary.append(
			{
				"class": name,
				"stock_account": stock_account,
				"variation_account": variation,
				"initial": sum(initial.values()),
				"final": final,
			}
		)
	if not summary:
		frappe.throw(
			_("No hay existencias ni saldos en el grupo 3 a {0}.").format(
				frappe.utils.formatdate(posting_date)
			)
		)
	result = {"lines": summary}
	if not cint(dry_run):
		result["journal_entry"] = draft_entry(
			company, posting_date, INVENTORY, _("Regularización de existencias"), lines
		)
	return result
