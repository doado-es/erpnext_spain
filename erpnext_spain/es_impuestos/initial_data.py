# Datos iniciales de impuestos (specs 03 §3-§4 y 09 §2-§3).
#
# Reglas (spec 09): funciones ensure_* idempotentes que crean lo que falta,
# identificándolo por un nombre estable (el título + la compañía), y nunca
# modifican ni borran lo que existe, aunque el usuario lo haya cambiado.
# Los tipos impositivos son los vigentes a 30/10/2026 **[verificar al cambiar
# la normativa]**: IVA 21/10/4 %, recargo de equivalencia 5,2/1,4/0,5 %.

import frappe
from frappe import _

from erpnext_spain.utils.gating import is_pgc_company

# Versión de los datos iniciales de compañía (Company.es_initial_data_version).
DATA_VERSION = 2

NATIONAL = "Nacional"
NATIONAL_RE = "Nacional con recargo de equivalencia"
NATIONAL_WITHHOLDING = "Nacional con retención"
# Intracomunitario por sentido de la operación (revisión del 31/10/2026): ERPNext
# elige la plantilla de impuestos del artículo por categoría, sin distinguir venta
# y compra, y la venta va exenta mientras la compra se autoliquida al tipo del
# artículo. Con una sola categoría, la fila del artículo que acierta en la compra
# estropea la venta (ver es_impuestos/item_tax.py).
INTRA_EU_SALES = "Entrega intracomunitaria"
INTRA_EU_PURCHASES = "Adquisición intracomunitaria"
OLD_INTRA_EU = "Intracomunitario"  # categoría única anterior (patch split_intra_eu_category)
EXTRA_EU = "Extracomunitario"
SPECIAL_TERRITORIES = "Canarias, Ceuta y Melilla"
TAX_CATEGORIES = (
	NATIONAL,
	NATIONAL_RE,
	NATIONAL_WITHHOLDING,
	INTRA_EU_SALES,
	INTRA_EU_PURCHASES,
	EXTRA_EU,
	SPECIAL_TERRITORIES,
)

# Cuentas que la app añade al plan PGC si no existen (número, nombre, grupo, tipo).
EXTRA_ACCOUNTS = (("4771", "Hacienda Pública, IVA repercutido por recargo de equivalencia", "477", "Tax"),)

VAT_OUT, RE_OUT, VAT_IN = "4770", "4771", "4720"
WITHHELD_FROM_US = "4730"  # retenciones que nos practican los clientes (soportadas)
NON_DEDUCTIBLE_VAT = "6310"  # IVA no deducible como mayor gasto **[revisión contable]**


def vat(rate, classification="S1", operation="Interior", regime="01", account=VAT_OUT, **extra):
	return {
		"account": account,
		"rate": rate,
		"description": f"IVA {fmt(rate)} %",
		"es_tax_type": "IVA",
		"es_vat_classification": classification,
		"es_operation_type": operation,
		"es_regime_key": regime,
		**extra,
	}


def equivalence_surcharge(rate):
	return {
		"account": RE_OUT,
		"rate": rate,
		"description": f"Recargo de equivalencia {fmt(rate)} %",
		"es_tax_type": "Recargo de equivalencia",
		"es_vat_classification": "S1",
		"es_operation_type": "Interior",
	}


def withholding(rate):
	"""Retención que nos practica el cliente: línea de tipo negativo a la 473
	(Sales Taxes and Charges no tiene add_deduct_tax, spec 08 §4)."""
	return {
		"account": WITHHELD_FROM_US,
		"rate": -rate,
		"description": f"Retención IRPF {fmt(rate)} %",
		"es_tax_type": "Retención IRPF",
		"es_withholding_key": "Actividades profesionales",
	}


def fmt(rate) -> str:
	return f"{rate:g}".replace(".", ",")


SALES_TEMPLATES = (
	{"title": "IVA 21 %", "is_default": 1, "tax_category": NATIONAL, "rows": [vat(21)]},
	{"title": "IVA 10 %", "rows": [vat(10)]},
	{"title": "IVA 4 %", "rows": [vat(4)]},
	{
		"title": "IVA 21 % + RE 5,2 %",
		"tax_category": NATIONAL_RE,
		"rows": [vat(21), equivalence_surcharge(5.2)],
	},
	{"title": "IVA 10 % + RE 1,4 %", "rows": [vat(10), equivalence_surcharge(1.4)]},
	{"title": "IVA 4 % + RE 0,5 %", "rows": [vat(4), equivalence_surcharge(0.5)]},
	{
		"title": "IVA 21 % con retención 15 %",
		"tax_category": NATIONAL_WITHHOLDING,
		"rows": [vat(21), withholding(15)],
	},
	{"title": "IVA 21 % con retención 7 %", "rows": [vat(21), withholding(7)]},
	{"title": "Exenta", "rows": [vat(0, "E1") | {"description": "Operación exenta"}]},
	{
		"title": "Entrega intracomunitaria",
		"tax_category": INTRA_EU_SALES,
		"rows": [
			vat(0, "E5", "Entrega intracomunitaria") | {"description": "Entrega intracomunitaria exenta"}
		],
	},
	{
		"title": "Exportación",
		"tax_category": EXTRA_EU,
		"rows": [vat(0, "E2", "Exportación", "02") | {"description": "Exportación exenta"}],
	},
	{
		"title": "Inversión del sujeto pasivo",
		"rows": [vat(0, "S2") | {"description": "Inversión del sujeto pasivo"}],
	},
	{
		"title": "No sujeta por localización",
		"rows": [vat(0, "N2", "Servicios a/desde fuera de la UE") | {"description": "Operación no sujeta"}],
	},
)


def vat_in(rate, deductibility="Corriente", classification="S1", operation="Interior", **extra):
	row = vat(rate, classification, operation, account=VAT_IN, **extra)
	row.update(description=f"IVA soportado {fmt(rate)} %", es_deductibility=deductibility)
	return row


def self_assessed(rate, classification, operation):
	"""Pareja de líneas de autorrepercusión (ISP, adquisiciones intracomunitarias):
	IVA soportado deducible a la 4720 y el mismo importe devengado a la 4770, que se
	resta. La factura del proveedor no cambia de total y el asiento queda hecho con
	la propia factura, sin código en la contabilización."""
	return [
		vat_in(rate, "Corriente", classification, operation)
		| {"description": f"IVA soportado {fmt(rate)} % (autorrepercusión)"},
		vat(rate, classification, operation, account=VAT_OUT)
		| {
			"description": f"IVA devengado {fmt(rate)} % (autorrepercusión)",
			"add_deduct_tax": "Deduct",
			"es_self_assessed": 1,
		},
	]


PURCHASE_TEMPLATES = (
	{"title": "IVA soportado 21 %", "is_default": 1, "tax_category": NATIONAL, "rows": [vat_in(21)]},
	{"title": "IVA soportado 10 %", "rows": [vat_in(10)]},
	{"title": "IVA soportado 4 %", "rows": [vat_in(4)]},
	{"title": "IVA soportado 21 % bien de inversión", "rows": [vat_in(21, "Bien de inversión")]},
	{"title": "IVA soportado 10 % bien de inversión", "rows": [vat_in(10, "Bien de inversión")]},
	{"title": "IVA soportado 4 % bien de inversión", "rows": [vat_in(4, "Bien de inversión")]},
	{
		"title": "IVA soportado 21 % no deducible",
		"rows": [vat_in(21, "No deducible") | {"account": NON_DEDUCTIBLE_VAT}],
	},
	{
		"title": "Exenta (compras)",
		"rows": [vat_in(0, "Corriente", "E1") | {"description": "Operación exenta"}],
	},
	{
		"title": "Adquisición intracomunitaria de bienes 21 %",
		"tax_category": INTRA_EU_PURCHASES,
		"rows": self_assessed(21, "S1", "Adquisición intracomunitaria de bienes"),
	},
	{
		"title": "Adquisición intracomunitaria de servicios 21 %",
		"rows": self_assessed(21, "S1", "Adquisición intracomunitaria de servicios"),
	},
	{
		"title": "Inversión del sujeto pasivo 21 % (compras)",
		"rows": self_assessed(21, "S2", "Interior"),
	},
)

# ERPNext admite una sola plantilla por categoría fiscal y compañía: la llevan
# solo las plantillas a las que apuntan las reglas de impuestos.

# Plantillas de impuestos de artículo: cambian el tipo de las líneas de la
# plantilla de la factura para los artículos que no tributan al general.
ITEM_TAX_TEMPLATES = (
	{"title": "IVA 10 %", "es_vat_classification": "S1", "rates": {VAT_OUT: 10, RE_OUT: 1.4, VAT_IN: 10}},
	{"title": "IVA 4 %", "es_vat_classification": "S1", "rates": {VAT_OUT: 4, RE_OUT: 0.5, VAT_IN: 4}},
	{"title": "IVA 0 %", "es_vat_classification": "S1", "rates": {VAT_OUT: 0, RE_OUT: 0, VAT_IN: 0}},
	{"title": "Exento", "es_vat_classification": "E1", "rates": {VAT_OUT: 0, RE_OUT: 0, VAT_IN: 0}},
	# Suplidos y otras líneas sin retención en facturas con retención (spec 08 §4).
	{"title": "Sin retención", "rates": {WITHHELD_FROM_US: 0}},
)

SALES_RULES = (
	(NATIONAL, "IVA 21 %"),
	(NATIONAL_RE, "IVA 21 % + RE 5,2 %"),
	(NATIONAL_WITHHOLDING, "IVA 21 % con retención 15 %"),
	(INTRA_EU_SALES, "Entrega intracomunitaria"),
	(EXTRA_EU, "Exportación"),
	(SPECIAL_TERRITORIES, "Exportación"),
)
PURCHASE_RULES = (
	(NATIONAL, "IVA soportado 21 %"),
	(NATIONAL_WITHHOLDING, "IVA soportado 21 %"),
	(NATIONAL_RE, "IVA soportado 21 %"),
	(INTRA_EU_PURCHASES, "Adquisición intracomunitaria de bienes 21 %"),
)

# Cuenta por defecto de cada modo de pago estándar de ERPNext.
MODE_OF_PAYMENT_ACCOUNTS = {
	"Cash": "5700",
	"Wire Transfer": "5720",
	"Credit Card": "5720",
	"Cheque": "5720",
	"Bank Draft": "5720",
	# Modos que añade la app (erpnext_spain/initial_data.py).
	"Domiciliación bancaria": "5720",
	"Confirming": "5720",
	"Bizum": "5720",
}

CLASSIFICATION_FIELDS = (
	"es_tax_type",
	"es_vat_classification",
	"es_operation_type",
	"es_regime_key",
	"es_withholding_key",
	"es_deductibility",
	"es_self_assessed",
)


# --- Registros globales (after_install / after_migrate) ---------------------


def ensure_global_records() -> None:
	for name in TAX_CATEGORIES:
		if not frappe.db.exists("Tax Category", name):
			frappe.get_doc({"doctype": "Tax Category", "title": name}).insert(ignore_permissions=True)


# --- Registros de compañía ---------------------------------------------------


def setup_company(company: str, chart_model: str | None = None) -> None:
	"""Paso de «Aplicar plan PGC» (pgc.COMPANY_SETUP_STEPS)."""
	ensure_company_records(company)


@frappe.whitelist(methods=["POST"])
def create_missing_company_records(company: str) -> dict:
	"""Crea los registros de impuestos que falten en una compañía con el plan PGC
	ya aplicado (p. ej. aplicado antes de que existieran). No modifica nada."""
	from erpnext_spain.es_contabilidad.pgc import check_permissions

	check_permissions(company)
	if not is_pgc_company(company):
		frappe.throw(
			_("La compañía {0} no tiene el plan PGC aplicado. Aplíquelo primero.").format(
				frappe.bold(company)
			)
		)
	from erpnext_spain.erpnext_spain.initial_data import setup_company as setup_base
	from erpnext_spain.es_retenciones.setup import setup_company as setup_withholding

	created = {"Bank Transaction Rule": setup_base(company)}
	created.update(ensure_company_records(company))
	created["Tax Withholding Category"] = setup_withholding(company)
	return created


def ensure_company_records(company: str) -> dict:
	ensure_global_records()
	created = {"accounts": ensure_extra_accounts(company)}
	created["Sales Taxes and Charges Template"] = ensure_tax_templates(
		company, "Sales Taxes and Charges Template", SALES_TEMPLATES
	)
	created["Purchase Taxes and Charges Template"] = ensure_tax_templates(
		company, "Purchase Taxes and Charges Template", PURCHASE_TEMPLATES
	)
	created["Item Tax Template"] = ensure_item_tax_templates(company)
	created["Tax Rule"] = ensure_tax_rules(company)
	created["Mode of Payment Account"] = ensure_mode_of_payment_accounts(company)
	current = frappe.db.get_value("Company", company, "es_initial_data_version") or 0
	if current < DATA_VERSION:
		frappe.db.set_value("Company", company, "es_initial_data_version", DATA_VERSION)
	return created


def account(company: str, number: str) -> str:
	name = frappe.db.get_value("Account", {"company": company, "account_number": number}, "name")
	if not name:
		frappe.throw(
			_("Falta la cuenta {0} en la compañía {1}; los datos de impuestos la necesitan.").format(
				number, frappe.bold(company)
			)
		)
	return name


def ensure_extra_accounts(company: str) -> list[str]:
	created = []
	for number, name, parent_number, account_type in EXTRA_ACCOUNTS:
		if frappe.db.exists("Account", {"company": company, "account_number": number}):
			continue
		parent = account(company, parent_number)
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"company": company,
				"account_name": name,
				"account_number": number,
				"parent_account": parent,
				"account_type": account_type,
				"is_group": 0,
			}
		)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)
	return created


def ensure_tax_templates(company: str, doctype: str, templates) -> list[str]:
	created = []
	cost_center = frappe.get_cached_value("Company", company, "cost_center")
	for spec in templates:
		if frappe.db.exists(doctype, {"company": company, "title": spec["title"]}):
			continue
		rows = []
		for row in spec["rows"]:
			line = {
				"charge_type": "On Net Total",
				"account_head": account(company, row["account"]),
				"rate": row["rate"],
				"description": row["description"],
				"cost_center": cost_center,
				**{field: row[field] for field in CLASSIFICATION_FIELDS if field in row},
			}
			if doctype == "Purchase Taxes and Charges Template":
				line["category"] = "Total"
				line["add_deduct_tax"] = row.get("add_deduct_tax", "Add")
			rows.append(line)
		doc = frappe.get_doc(
			{
				"doctype": doctype,
				"title": spec["title"],
				"company": company,
				"is_default": spec.get("is_default", 0),
				"tax_category": spec.get("tax_category"),
				"taxes": rows,
			}
		)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)
	return created


def ensure_item_tax_templates(company: str) -> list[str]:
	created = []
	for spec in ITEM_TAX_TEMPLATES:
		if frappe.db.exists("Item Tax Template", {"company": company, "title": spec["title"]}):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Item Tax Template",
				"title": spec["title"],
				"company": company,
				"es_vat_classification": spec.get("es_vat_classification"),
				"taxes": [
					{"tax_type": account(company, number), "tax_rate": rate}
					for number, rate in spec["rates"].items()
				],
			}
		)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)
	return created


def template_name(company: str, doctype: str, title: str) -> str:
	return frappe.db.get_value(doctype, {"company": company, "title": title}, "name")


def ensure_tax_rules(company: str) -> list[str]:
	created = []
	for tax_type, rules, doctype, field in (
		("Sales", SALES_RULES, "Sales Taxes and Charges Template", "sales_tax_template"),
		("Purchase", PURCHASE_RULES, "Purchase Taxes and Charges Template", "purchase_tax_template"),
	):
		for tax_category, title in rules:
			if frappe.db.exists(
				"Tax Rule", {"company": company, "tax_type": tax_type, "tax_category": tax_category}
			):
				continue
			template = template_name(company, doctype, title)
			if not template:
				# El usuario borró o renombró la plantilla: no se recrea la regla.
				continue
			doc = frappe.get_doc(
				{
					"doctype": "Tax Rule",
					"company": company,
					"tax_type": tax_type,
					"tax_category": tax_category,
					field: template,
					"priority": 1,
				}
			)
			doc.insert(ignore_permissions=True)
			created.append(doc.name)
	return created


def ensure_mode_of_payment_accounts(company: str) -> list[str]:
	created = []
	for mode, number in MODE_OF_PAYMENT_ACCOUNTS.items():
		if not frappe.db.exists("Mode of Payment", mode):
			continue
		if frappe.db.exists("Mode of Payment Account", {"parent": mode, "company": company}):
			continue
		doc = frappe.get_doc("Mode of Payment", mode)
		doc.append("accounts", {"company": company, "default_account": account(company, number)})
		doc.save(ignore_permissions=True)
		created.append(mode)
	return created
