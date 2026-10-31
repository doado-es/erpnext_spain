# Custom fields del SII en Company (spec 14 §1). Solo la activación por
# empresa: el envío de registros a la AEAT es trabajo de la spec 14.
#
# SII y VeriFactu son excluyentes por compañía (decisión del 30/10/2026, opción
# A): dos casillas y una validación en Company (es_sii/company.py), más una
# comprobación en tiempo de ejecución (utils/gating.active_billing_system).

from __future__ import annotations

AUTOMATIC, MANUAL = "Automático", "Manual"

COMPANY_FIELDS = [
	{
		"fieldname": "es_sii_section",
		"label": "SII",
		"fieldtype": "Section Break",
		"insert_after": "es_invoice_series",
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
		"description": "Las facturas con fecha de registro contable anterior no se envían al SII.",
	},
	{
		"fieldname": "es_sii_end_date",
		"label": "Fecha de fin en el SII",
		"fieldtype": "Date",
		"insert_after": "es_sii_activation_date",
		"depends_on": "eval:doc.es_sii_enabled",
		"description": (
			"Las facturas con fecha de registro contable posterior no se envían al SII. Los"
			" registros pendientes de antes de esa fecha se siguen enviando."
		),
	},
	{
		"fieldname": "es_sii_sending_section",
		"label": "Envío al SII",
		"fieldtype": "Section Break",
		"insert_after": "es_sii_end_date",
		"depends_on": "eval:doc.es_sii_enabled",
	},
	{
		"fieldname": "es_sii_strategy",
		"label": "Estrategia de envío",
		"fieldtype": "Select",
		"options": f"{AUTOMATIC}\n{MANUAL}",
		"default": AUTOMATIC,
		"insert_after": "es_sii_sending_section",
		"description": (
			"Automático: un trabajo programado envía cada factura cuando han pasado los días"
			" hábiles de espera. Manual: se envían desde las listas de facturas (acción «Enviar"
			" al SII»)."
		),
	},
	{
		"fieldname": "es_sii_wait_days",
		"label": "Días hábiles de espera",
		"fieldtype": "Int",
		"default": "0",
		"non_negative": 1,
		"insert_after": "es_sii_strategy",
		"depends_on": f"eval:doc.es_sii_strategy == '{AUTOMATIC}'",
		"description": (
			"Días hábiles desde la fecha de registro contable (emitidas y recibidas). 0: en el"
			" siguiente ciclo. Si el plazo legal vence antes, la factura se envía al vencer."
			" Las modificaciones y las bajas se envían sin esperar."
		),
	},
	{
		"fieldname": "es_sii_sending_column",
		"fieldtype": "Column Break",
		"insert_after": "es_sii_wait_days",
	},
	{
		"fieldname": "es_sii_notify_email",
		"label": "Avisar por correo",
		"fieldtype": "Check",
		"insert_after": "es_sii_sending_column",
		"description": "Correo a los usuarios con los roles de notificación con el resultado de cada envío y los avisos de plazo.",
	},
	{
		"fieldname": "es_sii_notify_desktop",
		"label": "Avisar en el escritorio",
		"fieldtype": "Check",
		"default": "1",
		"insert_after": "es_sii_notify_email",
		"description": "Aviso emergente en el escritorio de los usuarios conectados con esos roles.",
	},
]

CUSTOM_FIELDS = {"Company": COMPANY_FIELDS}
FIELDS_PER_DOCTYPE = {"Company": [field["fieldname"] for field in COMPANY_FIELDS]}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)
	fill_default_strategy()


def fill_default_strategy() -> None:
	"""Compañías existentes sin estrategia: automático (el comportamiento anterior)."""
	import frappe

	if not frappe.db.has_column("Company", "es_sii_strategy"):
		return
	company = frappe.qb.DocType("Company")
	frappe.qb.update(company).set(company.es_sii_strategy, AUTOMATIC).where(
		company.es_sii_strategy.isnull() | (company.es_sii_strategy == "")
	).run()


def cleanup_custom_fields() -> None:
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	_cleanup(FIELDS_PER_DOCTYPE)
