# Custom fields del módulo ES Contabilidad (spec 04 §6-§7).

from erpnext_spain.es_contabilidad.closing import CLOSING_TYPES, DEFAULT_INVENTORY_CLASS, INVENTORY_CLASSES

CUSTOM_FIELDS = {
	"Journal Entry": [
		{
			"fieldname": "es_closing_type",
			"label": "Asiento de cierre PGC",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(CLOSING_TYPES),
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "voucher_type",
			"depends_on": "eval:doc.es_closing_type",
		},
	],
	"Item Group": [
		{
			"fieldname": "es_inventory_class",
			"label": "Clase de existencias (PGC)",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(INVENTORY_CLASSES),
			"insert_after": "parent_item_group",
			"description": (
				f"Cuentas de existencias y de variación en la regularización de cierre. Vacío: {DEFAULT_INVENTORY_CLASS}"
				" (300/610)."
			),
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
