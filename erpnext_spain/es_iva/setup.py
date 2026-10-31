# Custom fields del módulo ES Iva (spec 06).


def party_fields(insert_after: str) -> list[dict]:
	"""Datos del tercero que el desglose necesita, congelados al validar (spec 06)."""
	return [
		{
			"fieldname": "es_party_country",
			"label": "País del tercero (fiscal)",
			"fieldtype": "Link",
			"options": "Country",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": insert_after,
		},
		{
			"fieldname": "es_id_type",
			"label": "Tipo de identificación del tercero",
			"fieldtype": "Data",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "es_party_country",
			"description": "Vacío: NIF español. 02: NIF-IVA de la UE. 06: otro documento.",
		},
	]


CUSTOM_FIELDS = {
	"Sales Invoice": party_fields("tax_id"),
	"Purchase Invoice": [
		*party_fields("tax_id"),
		{
			"fieldname": "es_pro_rata",
			"label": "Prorrata de IVA aplicada (%)",
			"fieldtype": "Percent",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "es_id_type",
		},
	],
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
