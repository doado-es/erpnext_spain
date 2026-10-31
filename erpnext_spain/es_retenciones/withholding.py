# Retenciones practicadas: validaciones y clasificación (spec 08 §3).
#
# - Supplier.validate: si el proveedor tiene categoría de la app y un grupo sin
#   fila de tipo en ella, error al guardar el proveedor (no al facturar).
# - Purchase Invoice / Payment Entry .validate (después del cálculo nativo de
#   ERPNext): las filas con is_tax_withholding_account se clasifican como
#   «Retención IRPF» con la clave de la categoría. En compras, la categoría de
#   arrendamientos exige el inmueble al validar (submit).

import frappe
from frappe import _
from frappe.utils import cstr

from erpnext_spain.es_impuestos.codes import TAX_TYPES
from erpnext_spain.es_retenciones.setup import is_leasing_category
from erpnext_spain.utils.gating import is_pgc_company

IRPF = TAX_TYPES["IRPF"]


def validate_supplier(doc, method=None) -> None:
	category = doc.get("tax_withholding_category")
	if not category:
		return
	if not frappe.get_cached_value("Tax Withholding Category", category, "es_tax_model"):
		return  # categoría ajena a la app: comportamiento estándar
	group = cstr(doc.get("tax_withholding_group"))
	rows = frappe.get_cached_doc("Tax Withholding Category", category).rates
	if not any(cstr(row.tax_withholding_group) == group for row in rows):
		available = sorted({cstr(row.tax_withholding_group) or _("General (sin grupo)") for row in rows})
		frappe.throw(
			_(
				"La categoría de retención {0} no tiene tipo para el grupo {1}, así que sus facturas"
				" no se podrían calcular. Elija uno de estos grupos: {2}, o añada la fila de tipo en la"
				" categoría."
			).format(
				frappe.bold(category), frappe.bold(group or _("General (sin grupo)")), ", ".join(available)
			),
			title=_("Grupo de retención sin tipo"),
		)


def validate_purchase_invoice(doc, method=None) -> None:
	if not is_pgc_company(doc.company):
		return
	categories = set()
	if doc.get("apply_tds"):
		categories = {item.tax_withholding_category for item in doc.items if item.get("apply_tds")}
		categories.discard(None)
	classify_withholding_rows(doc.get("taxes"), categories)
	if doc.docstatus == 1 and any(is_leasing_category(c) for c in categories):
		check_leased_property(doc)


def validate_payment_entry(doc, method=None) -> None:
	if not is_pgc_company(doc.company):
		return
	categories = (
		{doc.tax_withholding_category}
		if doc.get("apply_tds") and doc.get("tax_withholding_category")
		else set()
	)
	classify_withholding_rows(doc.get("taxes"), categories)


def classify_withholding_rows(rows, categories: set[str]) -> None:
	if not rows:
		return
	keys = {frappe.get_cached_value("Tax Withholding Category", c, "es_irpf_key") for c in categories}
	keys.discard(None)
	key = keys.pop() if len(keys) == 1 else None  # varias claves en una fila: se deja para revisar
	for row in rows:
		if not row.get("is_tax_withholding_account"):
			continue
		if not row.get("es_tax_type"):
			row.es_tax_type = IRPF
		if key and not row.get("es_withholding_key"):
			row.es_withholding_key = key


def check_leased_property(doc) -> None:
	if not doc.get("es_leased_property"):
		frappe.throw(
			_(
				"La factura tiene retención por arrendamiento de inmuebles: indique el inmueble"
				" arrendado (campo «Inmueble arrendado»). El modelo 180 lo necesita. Si el inmueble no"
				" existe, créelo en «Inmueble arrendado»."
			),
			title=_("Falta el inmueble"),
		)
	lessor, company = frappe.get_cached_value(
		"ES Leased Property", doc.es_leased_property, ["lessor", "company"]
	)
	if lessor != doc.supplier or company != doc.company:
		frappe.throw(
			_("El inmueble {0} es de otro arrendador o de otra compañía. Elija un inmueble de {1}.").format(
				frappe.bold(doc.es_leased_property), frappe.bold(doc.supplier)
			),
			title=_("Inmueble de otro arrendador"),
		)
