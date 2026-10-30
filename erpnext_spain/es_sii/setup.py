# Custom fields del SII en Company (spec 14 §1). Solo la activación por
# empresa: el envío de registros a la AEAT es trabajo de la spec 14.
#
# SII y VeriFactu son excluyentes por compañía (decisión del 30/10/2026, opción
# A): dos casillas y una validación en Company (es_sii/company.py), más una
# comprobación en tiempo de ejecución (utils/gating.active_billing_system).

from __future__ import annotations

COMPANY_FIELDS = [
	{
		"fieldname": "es_sii_section",
		"label": "SII",
		"fieldtype": "Section Break",
		"insert_after": "es_verifactu_notification_roles",
	},
	{
		"fieldname": "es_sii_enabled",
		"label": "SII activado",
		"fieldtype": "Check",
		"insert_after": "es_sii_section",
		"description": (
			"Suministro Inmediato de Información del IVA, para empresas obligadas o adheridas."
			" Excluyente con VeriFactu: quien lleva los libros por el SII queda fuera de VeriFactu."
		),
	},
	{
		"fieldname": "es_sii_test_mode",
		"label": "Modo operativo",
		"fieldtype": "Select",
		"options": "Pruebas\nProducción",
		"default": "Pruebas",
		"insert_after": "es_sii_enabled",
		"depends_on": "eval:doc.es_sii_enabled",
		"description": (
			"Pruebas: los envíos van al entorno de pruebas de la AEAT y NO tienen validez fiscal."
			" Producción: envíos reales."
		),
	},
	{
		"fieldname": "es_sii_column",
		"fieldtype": "Column Break",
		"insert_after": "es_sii_test_mode",
	},
	{
		"fieldname": "es_sii_activation_date",
		"label": "Fecha de inicio en el SII",
		"fieldtype": "Date",
		"insert_after": "es_sii_column",
		"depends_on": "eval:doc.es_sii_enabled",
	},
	{
		"fieldname": "es_sii_credential",
		"label": "Credencial AEAT (SII)",
		"fieldtype": "Link",
		"options": "ES AEAT Credential",
		"insert_after": "es_sii_activation_date",
		"depends_on": "eval:doc.es_sii_enabled",
		"description": "Certificado digital de la empresa con propósito SII.",
	},
]

CUSTOM_FIELDS = {"Company": COMPANY_FIELDS}
FIELDS_PER_DOCTYPE = {"Company": [field["fieldname"] for field in COMPANY_FIELDS]}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)


def cleanup_custom_fields() -> None:
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	_cleanup(FIELDS_PER_DOCTYPE)
