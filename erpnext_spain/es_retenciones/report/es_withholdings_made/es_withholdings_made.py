# Retenciones practicadas (spec 08 §6): vista previa de las casillas de los
# modelos 111 y 115 y de los registros de los resúmenes 190 y 180.
#
# Fuente: Tax Withholding Entry (facturas de compra, pagos y asientos), sin los
# estados Cancelled ni Duplicate. Periodo por fecha de la retención (documento
# que retiene). **Decisión A7 pendiente**: agrupar por fecha de pago.

import frappe
from frappe import _
from frappe.query_builder.functions import Sum


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Elija la compañía."))
	return get_columns(), get_data(filters)


def get_columns() -> list[dict]:
	return [
		{"fieldname": "tax_model", "label": _("Modelo"), "fieldtype": "Data", "width": 70},
		{
			"fieldname": "category",
			"label": _("Categoría"),
			"fieldtype": "Link",
			"options": "Tax Withholding Category",
			"width": 220,
		},
		{"fieldname": "key_190", "label": _("Clave 190"), "fieldtype": "Data", "width": 70},
		{"fieldname": "subkey_190", "label": _("Subclave"), "fieldtype": "Data", "width": 70},
		{"fieldname": "party_type", "label": _("Tipo de tercero"), "fieldtype": "Data", "hidden": 1},
		{
			"fieldname": "party",
			"label": _("Perceptor"),
			"fieldtype": "Dynamic Link",
			"options": "party_type",
			"width": 180,
		},
		{"fieldname": "party_name", "label": _("Nombre"), "fieldtype": "Data", "width": 200},
		{"fieldname": "tax_id", "label": _("NIF"), "fieldtype": "Data", "width": 110},
		{"fieldname": "province", "label": _("Provincia"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "taxable_amount",
			"label": _("Base de retención"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{"fieldname": "withholding_amount", "label": _("Retención"), "fieldtype": "Currency", "width": 120},
	]


def get_data(filters) -> list[dict]:
	entry = frappe.qb.DocType("Tax Withholding Entry")
	category = frappe.qb.DocType("Tax Withholding Category")
	query = (
		frappe.qb.from_(entry)
		.join(category)
		.on(category.name == entry.tax_withholding_category)
		.select(
			category.es_tax_model.as_("tax_model"),
			entry.tax_withholding_category.as_("category"),
			category.es_key_190.as_("key_190"),
			category.es_subkey_190.as_("subkey_190"),
			entry.party_type,
			entry.party,
			entry.tax_id,
			Sum(entry.taxable_amount).as_("taxable_amount"),
			Sum(entry.withholding_amount).as_("withholding_amount"),
		)
		.where(entry.company == filters.company)
		.where(entry.docstatus == 1)
		.where(entry.status.notin(["Cancelled", "Duplicate"]))
		.where(entry.withholding_amount != 0)
		.groupby(entry.tax_withholding_category, entry.party_type, entry.party, entry.tax_id)
		.orderby(category.es_tax_model)
		.orderby(entry.tax_withholding_category)
		.orderby(entry.party)
	)
	if filters.get("from_date"):
		query = query.where(entry.withholding_date >= filters.from_date)
	if filters.get("to_date"):
		query = query.where(entry.withholding_date <= filters.to_date)
	if filters.get("tax_model"):
		query = query.where(category.es_tax_model == filters.tax_model)
	if filters.get("category"):
		query = query.where(entry.tax_withholding_category == filters.category)
	if filters.get("party"):
		query = query.where(entry.party == filters.party)

	rows = query.run(as_dict=True)
	add_party_details(rows)
	return rows


def add_party_details(rows: list[dict]) -> None:
	for row in rows:
		if row.party_type != "Supplier":
			continue
		name, address = frappe.get_cached_value(
			"Supplier", row.party, ["supplier_name", "supplier_primary_address"]
		)
		row.party_name = name
		row.province = frappe.get_cached_value("Address", address, "state") if address else None
