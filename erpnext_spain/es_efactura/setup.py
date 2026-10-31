# Custom fields de la factura electrónica (spec 10) y de las rectificativas
# (spec 05 §2), que Facturae exige.

from __future__ import annotations

from erpnext_spain.es_efactura.codes import (
	CORRECTION_METHODS,
	PAYMENT_MEANS,
	PERSON_TYPES,
	REASONS,
	UNITS,
)


def select(catalog: dict) -> str:
	return "\n" + "\n".join(catalog)


def described(catalog: dict) -> str:
	return "; ".join(f"{code}: {label}" for code, label in catalog.items())


def person_fields(insert_after: str, prefix_label: str = "") -> list[dict]:
	return [
		{
			"fieldname": "es_person_type",
			"label": "Tipo de persona",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(PERSON_TYPES),
			"insert_after": insert_after,
			"description": "Si se deja vacío se deduce del NIF: DNI o NIE, persona física; CIF, jurídica.",
		},
		{
			"fieldname": "es_individual_name",
			"label": "Nombre",
			"fieldtype": "Data",
			"insert_after": "es_person_type",
			"depends_on": "eval:doc.es_person_type == 'Física'",
		},
		{
			"fieldname": "es_first_surname",
			"label": "Primer apellido",
			"fieldtype": "Data",
			"insert_after": "es_individual_name",
			"depends_on": "eval:doc.es_person_type == 'Física'",
		},
		{
			"fieldname": "es_second_surname",
			"label": "Segundo apellido",
			"fieldtype": "Data",
			"insert_after": "es_first_surname",
			"depends_on": "eval:doc.es_person_type == 'Física'",
		},
	]


CUSTOMER_FIELDS = [
	{
		"fieldname": "es_einvoice_section",
		"label": "Factura electrónica",
		"fieldtype": "Section Break",
		"collapsible": 1,
		"insert_after": "tax_category",
	},
	*person_fields("es_einvoice_section"),
	{
		"fieldname": "es_einvoice_column",
		"fieldtype": "Column Break",
		"insert_after": "es_second_surname",
	},
	{
		"fieldname": "es_public_administration",
		"label": "Administración Pública (FACe)",
		"fieldtype": "Check",
		"insert_after": "es_einvoice_column",
		"description": "Las facturas a este cliente se presentan en Facturae a través de FACe.",
	},
	{
		"fieldname": "es_dir3_accounting_office",
		"label": "DIR3 oficina contable",
		"fieldtype": "Data",
		"insert_after": "es_public_administration",
		"depends_on": "eval:doc.es_public_administration",
		"mandatory_depends_on": "eval:doc.es_public_administration",
	},
	{
		"fieldname": "es_dir3_managing_body",
		"label": "DIR3 órgano gestor",
		"fieldtype": "Data",
		"insert_after": "es_dir3_accounting_office",
		"depends_on": "eval:doc.es_public_administration",
		"mandatory_depends_on": "eval:doc.es_public_administration",
	},
	{
		"fieldname": "es_dir3_processing_unit",
		"label": "DIR3 unidad tramitadora",
		"fieldtype": "Data",
		"insert_after": "es_dir3_managing_body",
		"depends_on": "eval:doc.es_public_administration",
		"mandatory_depends_on": "eval:doc.es_public_administration",
	},
	{
		"fieldname": "es_dir3_proposing_body",
		"label": "DIR3 órgano proponente (opcional)",
		"fieldtype": "Data",
		"insert_after": "es_dir3_processing_unit",
		"depends_on": "eval:doc.es_public_administration",
	},
]

COMPANY_FIELDS = [
	{
		"fieldname": "es_einvoice_section",
		"label": "Factura electrónica",
		"fieldtype": "Section Break",
		"insert_after": "es_sii_activation_date",
	},
	*person_fields("es_einvoice_section"),
	# Factura electrónica B2B (spec 10 §5): obligatoria desde 2027-2028 (RD 238/2026).
	{
		"fieldname": "es_einvoice_b2b",
		"label": "Factura electrónica B2B",
		"fieldtype": "Check",
		"insert_after": "es_second_surname",
		"description": "Genera la factura electrónica UBL de las ventas a empresarios y profesionales españoles y recibe las de los proveedores.",
	},
	{
		"fieldname": "es_einvoice_channel",
		"label": "Canal B2B",
		"fieldtype": "Select",
		"options": "Descarga manual\nSPFE\nPlataforma privada\nSimulado",
		"default": "Descarga manual",
		"insert_after": "es_einvoice_b2b",
		"depends_on": "eval:doc.es_einvoice_b2b",
		"description": "SPFE de la AEAT o plataforma privada (decisión A9 pendiente). «Simulado» solo para pruebas.",
	},
]

SALES_INVOICE_FIELDS = [
	{
		"fieldname": "es_rectification_section",
		"label": "Rectificación",
		"fieldtype": "Section Break",
		"insert_after": "return_against",
		"depends_on": "eval:doc.is_return || (doc.es_invoice_type || '').startsWith('R')",
		"collapsible": 1,
	},
	{
		"fieldname": "es_rectification_reason_code",
		"label": "Motivo de la rectificación",
		"fieldtype": "Select",
		"options": select(REASONS),
		"insert_after": "es_rectification_section",
		"mandatory_depends_on": "eval:doc.is_return",
		"description": described(REASONS),
	},
	{
		"fieldname": "es_correction_method",
		"label": "Método de rectificación",
		"fieldtype": "Select",
		"options": select(CORRECTION_METHODS),
		"default": "02",
		"insert_after": "es_rectification_reason_code",
		"description": described(CORRECTION_METHODS),
	},
	# es_rectification_reason (la explicación) la define es_facturacion/setup.py,
	# después de es_rectification_method: un solo campo para Facturae y VeriFactu.
	{
		"fieldname": "es_einvoice",
		"label": "Factura electrónica",
		"fieldtype": "Link",
		"options": "ES E-Invoice",
		"read_only": 1,
		"allow_on_submit": 1,
		"no_copy": 1,
		# Pestaña «VeriFactu / SII» (es_facturacion/fiscal_tab.py).
		"insert_after": "es_fiscal_history_section",
	},
	{
		"fieldname": "es_einvoice_status",
		"label": "Estado de la factura electrónica",
		"fieldtype": "Data",
		"read_only": 1,
		"allow_on_submit": 1,
		"no_copy": 1,
		"in_standard_filter": 1,
		"insert_after": "es_einvoice",
	},
]

UOM_FIELDS = [
	{
		"fieldname": "es_facturae_unit",
		"label": "Unidad Facturae",
		"fieldtype": "Select",
		"options": select(UNITS),
		"insert_after": "must_be_whole_number",
		"description": described(UNITS) + ". Vacío: 01 (unidades).",
	}
]

MODE_OF_PAYMENT_FIELDS = [
	{
		"fieldname": "es_facturae_payment_means",
		"label": "Medio de pago Facturae",
		"fieldtype": "Select",
		"options": select(PAYMENT_MEANS),
		"insert_after": "type",
		"description": described(PAYMENT_MEANS) + ". Vacío: 04 (transferencia).",
	}
]

PURCHASE_INVOICE_FIELDS = [
	{
		"fieldname": "es_e_invoice",
		"label": "Factura electrónica recibida",
		"fieldtype": "Link",
		"options": "ES E-Invoice",
		"read_only": 1,
		"no_copy": 1,
		# Pestaña «SII / Factura electrónica» (es_facturacion/fiscal_tab.py).
		"insert_after": "es_fiscal_history_section",
	},
]

CUSTOM_FIELDS = {
	"Purchase Invoice": PURCHASE_INVOICE_FIELDS,
	"Customer": CUSTOMER_FIELDS,
	"Company": COMPANY_FIELDS,
	"Sales Invoice": SALES_INVOICE_FIELDS,
	"UOM": UOM_FIELDS,
	"Mode of Payment": MODE_OF_PAYMENT_FIELDS,
}
FIELDS_PER_DOCTYPE = {doctype: [f["fieldname"] for f in fields] for doctype, fields in CUSTOM_FIELDS.items()}

# Valores por defecto de los maestros estándar de ERPNext (no pisan lo que haya).
UOM_DEFAULTS = {"Nos": "01", "Unit": "01", "Hour": "02", "Kg": "03", "Litre": "04", "Box": "06", "Gram": "21"}
PAYMENT_MEANS_DEFAULTS = {"Cash": "01", "Wire Transfer": "04", "Cheque": "11", "Credit Card": "19"}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)


def ensure_defaults() -> None:
	import frappe

	for doctype, field, defaults in (
		("UOM", "es_facturae_unit", UOM_DEFAULTS),
		("Mode of Payment", "es_facturae_payment_means", PAYMENT_MEANS_DEFAULTS),
	):
		for name, code in defaults.items():
			if frappe.db.exists(doctype, name) and not frappe.db.get_value(doctype, name, field):
				frappe.db.set_value(doctype, name, field, code, update_modified=False)


def cleanup_custom_fields() -> None:
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	_cleanup(FIELDS_PER_DOCTYPE)
