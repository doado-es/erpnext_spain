# Custom fields de la clasificación fiscal (spec 03 §1): en las líneas de
# impuesto de venta y compra (las de plantilla y las de factura comparten
# doctype hijo) y en Item Tax Template.

from __future__ import annotations

from erpnext_spain.es_impuestos.codes import (
	DEDUCTIBILITY,
	OPERATION_TYPES,
	REGIME_KEYS,
	TAX_TYPES,
	VAT_CLASSIFICATIONS,
	WITHHOLDING_KEYS,
	describe,
	options,
)


def classification_fields(insert_after: str, purchase: bool) -> list[dict]:
	fields = [
		{
			"fieldname": "es_tax_section",
			"label": "Clasificación fiscal (España)",
			"fieldtype": "Section Break",
			"collapsible": 1,
			"insert_after": insert_after,
		},
		{
			"fieldname": "es_tax_type",
			"label": "Tipo de impuesto",
			"fieldtype": "Select",
			"options": options(TAX_TYPES.values()),
			"insert_after": "es_tax_section",
		},
		{
			"fieldname": "es_vat_classification",
			"label": "Calificación o exención",
			"fieldtype": "Select",
			"options": options(VAT_CLASSIFICATIONS),
			"insert_after": "es_tax_type",
			"depends_on": "eval:['IVA', 'Recargo de equivalencia'].includes(doc.es_tax_type)",
			"description": describe(VAT_CLASSIFICATIONS),
		},
		{
			"fieldname": "es_operation_type",
			"label": "Tipo de operación",
			"fieldtype": "Select",
			"options": options(OPERATION_TYPES),
			"insert_after": "es_vat_classification",
			"depends_on": "eval:['IVA', 'Recargo de equivalencia'].includes(doc.es_tax_type)",
		},
		{
			"fieldname": "es_tax_column",
			"fieldtype": "Column Break",
			"insert_after": "es_operation_type",
		},
		{
			"fieldname": "es_regime_key",
			"label": "Clave de régimen",
			"fieldtype": "Select",
			"options": options(REGIME_KEYS),
			"insert_after": "es_tax_column",
			"depends_on": "eval:doc.es_tax_type == 'IVA'",
			"description": describe(REGIME_KEYS),
		},
		{
			"fieldname": "es_withholding_key",
			"label": "Clave de retención",
			"fieldtype": "Select",
			"options": options(WITHHOLDING_KEYS),
			"insert_after": "es_regime_key",
			"depends_on": "eval:doc.es_tax_type == 'Retención IRPF'",
		},
	]
	if purchase:
		fields += [
			{
				"fieldname": "es_deductibility",
				"label": "Deducibilidad",
				"fieldtype": "Select",
				"options": options(DEDUCTIBILITY),
				"insert_after": "es_withholding_key",
				"depends_on": "eval:['IVA', 'Recargo de equivalencia'].includes(doc.es_tax_type)",
			},
			{
				"fieldname": "es_self_assessed",
				"label": "Autorrepercusión",
				"fieldtype": "Check",
				"insert_after": "es_deductibility",
				"description": (
					"Cuota que la empresa se repercute a sí misma (inversión del sujeto pasivo,"
					" adquisiciones intracomunitarias): IVA devengado, no soportado."
				),
			},
		]
	return fields


ITEM_TAX_TEMPLATE_FIELDS = [
	{
		"fieldname": "es_vat_classification",
		"label": "Calificación o exención",
		"fieldtype": "Select",
		"options": options(VAT_CLASSIFICATIONS),
		"insert_after": "company",
		"description": (
			"Sustituye a la de la línea de impuesto cuando la factura mezcla operaciones"
			" (p. ej. sujeta y exenta)."
		),
	},
	{
		"fieldname": "es_operation_type",
		"label": "Tipo de operación",
		"fieldtype": "Select",
		"options": options(OPERATION_TYPES),
		"insert_after": "es_vat_classification",
	},
]

# Impuestos de los pagos y anticipos (Payment Entry): solo tipo y clave de
# retención, para clasificar la retención de los anticipos (spec 08 §3).
ADVANCE_TAX_FIELDS = [
	{
		"fieldname": "es_tax_type",
		"label": "Tipo de impuesto",
		"fieldtype": "Select",
		"options": options(TAX_TYPES.values()),
		"insert_after": "is_tax_withholding_account",
	},
	{
		"fieldname": "es_withholding_key",
		"label": "Clave de retención",
		"fieldtype": "Select",
		"options": options(WITHHOLDING_KEYS),
		"insert_after": "es_tax_type",
		"depends_on": "eval:doc.es_tax_type == 'Retención IRPF'",
	},
]

CUSTOM_FIELDS = {
	"Sales Taxes and Charges": classification_fields("is_tax_withholding_account", purchase=False),
	"Advance Taxes and Charges": ADVANCE_TAX_FIELDS,
	"Purchase Taxes and Charges": classification_fields("column_break_odzz", purchase=True),
	"Item Tax Template": ITEM_TAX_TEMPLATE_FIELDS,
}

FIELDS_PER_DOCTYPE = {doctype: [f["fieldname"] for f in fields] for doctype, fields in CUSTOM_FIELDS.items()}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)


def cleanup_custom_fields() -> None:
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	_cleanup(FIELDS_PER_DOCTYPE)
