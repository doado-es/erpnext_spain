# Custom fields del módulo ES Iva (spec 06).

CUSTOM_FIELDS = {
	"Company": [
		{
			"fieldname": "es_vat_pro_rata",
			"label": "Prorrata general de IVA (%)",
			"fieldtype": "Percent",
			"insert_after": "es_doubtful_months",
			"description": (
				"Porcentaje de deducción del IVA soportado (prorrata general, art. 104 de la Ley 37/1992)."
				" Vacío o 100: se deduce todo."
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
