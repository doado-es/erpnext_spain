# Custom fields del módulo ES Sepa (spec 11-12).
#
# - Cuenta bancaria de la compañía: una fila por norma (transferencias SEPA,
#   adeudos SEPA, confirming) con su sufijo y, en confirming, el contrato.
# - Cuenta bancaria del cliente: el mandato de adeudo SEPA (esquema, fecha de
#   autorización, referencia y formulario firmado), como en spanish_compliance.

COMPANY_ACCOUNT = "eval:doc.is_company_account"
CUSTOMER_ACCOUNT = "eval:!doc.is_company_account && doc.party_type == 'Customer'"
MANDATE = "eval:doc.party_type == 'Customer' && doc.es_sepa_scheme"

CUSTOM_FIELDS = {
	"Company": [
		{
			"fieldname": "es_sepa_submit_payments",
			"label": "Validar los cobros de las remesas de adeudos",
			"fieldtype": "Check",
			"default": "1",
			"insert_after": "es_vat_pro_rata",
			"description": "Si no se marca, los cobros de cada remesa se crean en borrador.",
		},
	],
	"Bank Account": [
		{
			"fieldname": "es_norms_section",
			"label": "Normas bancarias",
			"fieldtype": "Section Break",
			# Justo después de los datos de la cuenta (IBAN), sin plegar.
			"insert_after": "statement_password",
			"depends_on": COMPANY_ACCOUNT,
			"collapsible": 0,
		},
		{
			"fieldname": "es_norms",
			"label": "Normas",
			"fieldtype": "Table",
			"options": "ES Bank Account Norm",
			"insert_after": "es_norms_section",
			"description": (
				"Datos que el banco asigna a esta cuenta para cada norma: transferencias SEPA (pain.001),"
				" adeudos SEPA (pain.008) y confirming AEF."
			),
		},
		{
			"fieldname": "es_mandate_section",
			"label": "Mandato SEPA",
			"fieldtype": "Section Break",
			"insert_after": "es_norms",
			"depends_on": CUSTOMER_ACCOUNT,
			"collapsible": 1,
		},
		{
			"fieldname": "es_sepa_scheme",
			"label": "Tipo SEPA autorizado",
			"fieldtype": "Select",
			"options": "\nCORE\nB2B",
			"insert_after": "es_mandate_section",
			"description": "Esquema de adeudo que autorizó el cliente. Vacío: la cuenta no admite adeudos.",
		},
		{
			"fieldname": "es_sepa_mandate_date",
			"label": "Fecha de autorización",
			"fieldtype": "Date",
			"insert_after": "es_sepa_scheme",
			"mandatory_depends_on": MANDATE,
		},
		{
			"fieldname": "es_sepa_mandate_reference",
			"label": "Referencia del mandato",
			"fieldtype": "Data",
			"length": 35,
			"insert_after": "es_sepa_mandate_date",
			"mandatory_depends_on": MANDATE,
			"description": "Única por acreedor, hasta 35 caracteres.",
		},
		{
			"fieldname": "es_sepa_mandate_type",
			"label": "Tipo de mandato",
			"fieldtype": "Select",
			"options": "Recurrente\nÚnico",
			"default": "Recurrente",
			"insert_after": "es_sepa_mandate_reference",
			"depends_on": MANDATE,
		},
		{
			"fieldname": "es_mandate_column",
			"fieldtype": "Column Break",
			"insert_after": "es_sepa_mandate_type",
		},
		{
			"fieldname": "es_sepa_mandate_form",
			"label": "Formulario de autorización",
			"fieldtype": "Attach",
			"insert_after": "es_mandate_column",
			"depends_on": MANDATE,
		},
		{
			"fieldname": "es_sepa_mandate_status",
			"label": "Estado del mandato",
			"fieldtype": "Select",
			"options": "Activo\nCancelado\nCaducado",
			"default": "Activo",
			"insert_after": "es_sepa_mandate_form",
			"depends_on": MANDATE,
		},
		{
			"fieldname": "es_sepa_last_debit",
			"label": "Fecha del último adeudo",
			"fieldtype": "Date",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "es_sepa_mandate_status",
			"depends_on": MANDATE,
			"description": "Un mandato sin adeudos durante 36 meses caduca.",
		},
		{
			"fieldname": "es_sepa_first_debit_done",
			"label": "Primer adeudo presentado",
			"fieldtype": "Check",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "es_sepa_last_debit",
			"depends_on": MANDATE,
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
		{"fieldname": "es_sepa_column", "fieldtype": "Column Break", "insert_after": "es_sepa_instant"},
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
# Campos de la primera versión que ya no se usan: se borran al migrar.
OBSOLETE_FIELDS = {
	"Company": ["es_sepa_creditor_suffix"],
	"Bank Account": ["es_sepa_suffix"],
	"Customer": ["es_sepa_mandate"],
}


def setup_custom_fields() -> None:
	import frappe
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	for doctype, fields in OBSOLETE_FIELDS.items():
		frappe.db.delete("Custom Field", {"dt": doctype, "fieldname": ["in", fields]})
	create_custom_fields(CUSTOM_FIELDS, update=True)


def cleanup_custom_fields() -> None:
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	_cleanup(FIELDS_PER_DOCTYPE)
