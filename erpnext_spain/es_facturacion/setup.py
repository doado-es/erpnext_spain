# Custom fields del módulo ES Facturacion (spec 05 §2 y §4).

import frappe

from erpnext_spain.es_facturacion import fiscal_tab
from erpnext_spain.es_facturacion.collection import STATUSES
from erpnext_spain.es_facturacion.numbering import METHOD_DIFFERENCES, RECTIFICATION_METHODS

RECTIFICATION_DEPENDS = "eval:doc.is_return || (doc.es_invoice_type || '').startsWith('R')"


def read_only_link(fieldname: str, label: str, insert_after: str, fieldtype: str = "Link") -> dict:
	field = {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": fieldtype,
		"read_only": 1,
		"allow_on_submit": 1,
		"no_copy": 1,
		"insert_after": insert_after,
	}
	if fieldtype == "Link":
		field["options"] = "Journal Entry"
	return field


CUSTOM_FIELDS = {
	"Sales Invoice": [
		{
			"fieldname": "es_rectification_method",
			"label": "Método de rectificación",
			"fieldtype": "Select",
			"options": "\n".join(RECTIFICATION_METHODS),
			"default": METHOD_DIFFERENCES,
			# En la sección «Rectificación» de la pestaña principal (es_efactura/setup.py).
			# Vale para VeriFactu y para Facturae (CorrectionMethod 02 o 01).
			"insert_after": "es_rectification_reason_code",
			"depends_on": RECTIFICATION_DEPENDS,
			"no_copy": 1,
		},
		{
			"fieldname": "es_rectification_reason",
			"label": "Motivo de la rectificación",
			"fieldtype": "Small Text",
			"insert_after": "es_rectification_method",
			"depends_on": RECTIFICATION_DEPENDS,
			"mandatory_depends_on": RECTIFICATION_DEPENDS,
			"no_copy": 1,
		},
		{
			"fieldname": "es_collection_section",
			"label": "Situación de cobro",
			"fieldtype": "Section Break",
			"insert_after": "es_rectification_reason",
			"collapsible": 1,
			"depends_on": "eval:doc.docstatus == 1 && doc.es_collection_status",
		},
		{
			"fieldname": "es_collection_status",
			"label": "Situación de cobro",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(STATUSES),
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
			"insert_after": "es_collection_section",
		},
		{
			"fieldname": "es_doubtful_amount",
			"label": "Importe pasado a dudoso cobro",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "es_collection_status",
		},
		read_only_link("es_doubtful_entry", "Asiento de dudoso cobro", "es_doubtful_amount"),
		{
			"fieldname": "es_collection_column",
			"fieldtype": "Column Break",
			"insert_after": "es_doubtful_entry",
		},
		{
			"fieldname": "es_impairment_amount",
			"label": "Deterioro dotado",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "es_collection_column",
		},
		read_only_link("es_impairment_entry", "Asiento de deterioro", "es_impairment_amount"),
		read_only_link("es_loss_entry", "Asiento de pérdida", "es_impairment_entry"),
		read_only_link("es_recovery_entry", "Asiento de recuperación", "es_loss_entry"),
		# Envío masivo por correo (spec 15, F3).
		{
			"fieldname": "es_emailed_on",
			"label": "Enviada por correo el",
			"fieldtype": "Datetime",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "es_recovery_entry",
		},
	],
	"Company": [
		{
			"fieldname": "es_doubtful_months",
			"label": "Meses para avisar de dudoso cobro",
			"fieldtype": "Int",
			"insert_after": "es_fiscal_numbering",
			"description": (
				"Si es mayor que 0, un aviso diario lista las facturas vencidas hace más de estos"
				" meses (no contabiliza nada). Plazo fiscal habitual: 6 meses."
			),
		},
	],
}

for _doctype, _fields in fiscal_tab.CUSTOM_FIELDS.items():
	CUSTOM_FIELDS.setdefault(_doctype, []).extend(_fields)

FIELDS_PER_DOCTYPE = {doctype: [f["fieldname"] for f in fields] for doctype, fields in CUSTOM_FIELDS.items()}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)


def cleanup_custom_fields() -> None:
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	_cleanup(FIELDS_PER_DOCTYPE)
	frappe.clear_cache(doctype="Sales Invoice")
	frappe.clear_cache(doctype="Purchase Invoice")
