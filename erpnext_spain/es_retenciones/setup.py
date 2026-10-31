# Configuración de las retenciones practicadas (spec 08 §3, spec 09).
#
# - Custom fields en Tax Withholding Category (modelo, claves del 190, clave de
#   retención) y en Purchase Invoice (inmueble arrendado).
# - Grupos de retención globales (`ensure_global_records`, after_install/after_migrate).
# - Categorías con sus filas de tipo y la cuenta 4751 de la compañía
#   (`setup_company`, paso de «Aplicar plan PGC» y botón «Crear impuestos que
#   faltan»). Se crean si faltan; no se pisan los cambios del usuario.

import frappe

from erpnext_spain.es_impuestos.codes import WITHHOLDING_KEYS, options
from erpnext_spain.es_retenciones.codes import (
	CATEGORIES,
	FROM_DATE,
	GROUPS,
	LEASING,
	TAX_MODELS,
	TO_DATE,
	WITHHOLDING_ACCOUNT,
)

CUSTOM_FIELDS = {
	"Tax Withholding Category": [
		{
			"fieldname": "es_withholding_section",
			"label": "España",
			"fieldtype": "Section Break",
			"insert_after": "disable_transaction_threshold",
		},
		{
			"fieldname": "es_tax_model",
			"label": "Modelo trimestral",
			"fieldtype": "Select",
			"options": options(TAX_MODELS),
			"insert_after": "es_withholding_section",
			"description": "111 (rendimientos del trabajo y actividades) o 115 (arrendamientos).",
		},
		{
			"fieldname": "es_irpf_key",
			"label": "Clave de retención",
			"fieldtype": "Select",
			"options": options(WITHHOLDING_KEYS),
			"insert_after": "es_tax_model",
			"description": "Se copia a la fila de retención de la factura.",
		},
		{
			"fieldname": "es_column_190",
			"fieldtype": "Column Break",
			"insert_after": "es_irpf_key",
		},
		{
			"fieldname": "es_key_190",
			"label": "Clave del modelo 190",
			"fieldtype": "Data",
			"length": 1,
			"insert_after": "es_column_190",
		},
		{
			"fieldname": "es_subkey_190",
			"label": "Subclave del modelo 190",
			"fieldtype": "Data",
			"length": 2,
			"insert_after": "es_key_190",
		},
	],
	"Purchase Invoice": [
		{
			"fieldname": "es_leased_property",
			"label": "Inmueble arrendado",
			"fieldtype": "Link",
			"options": "ES Leased Property",
			"insert_after": "tax_withholding_group",
			"depends_on": "eval:doc.apply_tds",
			"description": "Obligatorio si alguna línea usa la categoría de arrendamientos (modelo 180).",
		},
	],
}

FIELDS_PER_DOCTYPE = {doctype: [f["fieldname"] for f in fields] for doctype, fields in CUSTOM_FIELDS.items()}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)


def cleanup_custom_fields() -> None:
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	_cleanup(FIELDS_PER_DOCTYPE)


def ensure_global_records() -> list[str]:
	"""Grupos de retención. Idempotente."""
	created = []
	for group in GROUPS:
		if not frappe.db.exists("Tax Withholding Group", group):
			frappe.get_doc({"doctype": "Tax Withholding Group", "group_name": group}).insert(
				ignore_permissions=True
			)
			created.append(group)
	return created


def setup_company(company: str, chart_model: str | None = None) -> list[str]:
	"""Categorías de retención con la cuenta 4751 de la compañía.

	ERPNext v16 exige al menos una fila de cuenta, así que las categorías se crean
	con la primera compañía PGC y las siguientes añaden su fila. No se tocan los
	tipos ni las demás filas existentes. Devuelve las categorías creadas o
	completadas."""
	ensure_global_records()
	account = frappe.db.get_value(
		"Account", {"company": company, "account_number": WITHHOLDING_ACCOUNT}, "name"
	)
	if not account:
		return []
	changed = []
	for name, spec in CATEGORIES.items():
		if frappe.db.exists("Tax Withholding Category", name):
			doc = frappe.get_doc("Tax Withholding Category", name)
			if any(row.company == company for row in doc.accounts):
				continue
			doc.append("accounts", {"company": company, "account": account})
			doc.save(ignore_permissions=True)
		else:
			new_category(name, spec, company, account)
		changed.append(name)
	return changed


def new_category(name: str, spec: dict, company: str, account: str) -> None:
	doc = frappe.new_doc("Tax Withholding Category")
	doc.name = name
	doc.update(
		{
			"category_name": name,
			"tax_deduction_basis": "Net Total",
			"round_off_tax_amount": 0,
			"tax_on_excess_amount": 0,
			# Sin umbrales (en España se retiene siempre): umbral acumulado 0 SIN
			# desactivarlo. Con disable_cumulative_threshold, ERPNext solo retiene si
			# la base es >= umbral de la operación, y en una rectificativa la base es
			# negativa: no revertiría la retención [verificado v16.51,
			# TaxWithholdingController._is_threshold_crossed_for_category].
			"disable_cumulative_threshold": 0,
			"disable_transaction_threshold": 0,
			"es_tax_model": spec["model"],
			"es_irpf_key": spec["key"],
			"es_key_190": spec["key_190"],
			"es_subkey_190": spec["subkey_190"],
		}
	)
	for group, rate in spec["rates"].items():
		doc.append(
			"rates",
			{
				"tax_withholding_rate": rate,
				"from_date": FROM_DATE,
				"to_date": TO_DATE,
				"tax_withholding_group": group,
			},
		)
	doc.append("accounts", {"company": company, "account": account})
	doc.insert(ignore_permissions=True)


def is_leasing_category(category: str | None) -> bool:
	return category == LEASING
