# Custom fields del módulo ES Bancos (spec 13 §3).

CUSTOM_FIELDS = {
	"Bank Account": [
		{
			"fieldname": "es_bank_aggregator",
			"label": "Agregador bancario",
			"fieldtype": "Link",
			"options": "ES Bank Aggregator",
			"insert_after": "last_integration_date",
			"depends_on": "eval:doc.is_company_account",
		},
		{
			"fieldname": "es_consent_expiry",
			"label": "Caducidad del consentimiento",
			"fieldtype": "Date",
			"read_only": 1,
			"insert_after": "es_bank_aggregator",
			"depends_on": "eval:doc.es_bank_aggregator",
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
