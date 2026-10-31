# Custom fields del módulo ES Sepa (spec 11 §2-§6).

CUSTOM_FIELDS = {
	"Company": [
		{
			"fieldname": "es_sepa_creditor_suffix",
			"label": "Sufijo del identificador de acreedor SEPA",
			"fieldtype": "Data",
			"length": 3,
			"default": "000",
			"insert_after": "es_vat_pro_rata",
			"description": "Identificador de acreedor = ES + control + sufijo + NIF. Lo indica el banco (normalmente 000).",
		},
		{
			"fieldname": "es_sepa_submit_payments",
			"label": "Validar los cobros de las remesas de adeudos",
			"fieldtype": "Check",
			"default": "1",
			"insert_after": "es_sepa_creditor_suffix",
			"description": "Si no se marca, los cobros de cada remesa se crean en borrador.",
		},
	],
	"Bank Account": [
		{
			"fieldname": "es_sepa_suffix",
			"label": "Sufijo del presentador SEPA",
			"fieldtype": "Data",
			"length": 3,
			"default": "000",
			"insert_after": "iban",
			"depends_on": "eval:doc.is_company_account",
			"description": "Identificador del presentador de los ficheros: NIF de la compañía + este sufijo.",
		},
	],
	"Customer": [
		{
			"fieldname": "es_sepa_mandate",
			"label": "Mandato SEPA por defecto",
			"fieldtype": "Link",
			"options": "ES Sepa Mandate",
			"insert_after": "default_bank_account",
		},
	],
	"Payment Order": [
		{
			"fieldname": "es_sepa_section",
			"label": "SEPA",
			"fieldtype": "Section Break",
			"insert_after": "account",
			"collapsible": 1,
		},
		{
			"fieldname": "es_sepa_execution_date",
			"label": "Fecha de ejecución solicitada",
			"fieldtype": "Date",
			"insert_after": "es_sepa_section",
		},
		{
			"fieldname": "es_sepa_priority",
			"label": "Prioridad",
			"fieldtype": "Select",
			"options": "Normal\nUrgente",
			"default": "Normal",
			"insert_after": "es_sepa_execution_date",
		},
		{
			"fieldname": "es_sepa_instant",
			"label": "Transferencia inmediata",
			"fieldtype": "Check",
			"insert_after": "es_sepa_priority",
			"description": "Solo si el banco admite transferencias inmediatas por fichero.",
		},
		{
			"fieldname": "es_sepa_column",
			"fieldtype": "Column Break",
			"insert_after": "es_sepa_instant",
		},
		{
			"fieldname": "es_sepa_message_id",
			"label": "Identificador del mensaje",
			"fieldtype": "Data",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "es_sepa_column",
		},
		{
			"fieldname": "es_sepa_file",
			"label": "Fichero SEPA (pain.001)",
			"fieldtype": "Attach",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "es_sepa_message_id",
		},
	],
	"Payment Order Reference": [
		{
			"fieldname": "es_end_to_end_id",
			"label": "EndToEndId",
			"fieldtype": "Data",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "payment_reference",
		},
		{
			"fieldname": "es_sepa_status",
			"label": "Estado SEPA",
			"fieldtype": "Data",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "es_end_to_end_id",
		},
	],
	"Payment Entry": [
		{
			"fieldname": "es_end_to_end_id",
			"label": "EndToEndId SEPA",
			"fieldtype": "Data",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "reference_date",
			"search_index": 1,
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
