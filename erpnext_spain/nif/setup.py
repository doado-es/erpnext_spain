# Custom Fields declarados en código Python (doc 12 §11), con limpieza en
# before_uninstall (doc 12 §12). Idempotentes: after_install + after_migrate.
#
# - es_trade_name (spec 14): nombre comercial/marca del tercero, transversal
#   (es_, no es_verifactu_). Solo display — lo consumirán print formats vía
#   jinja en un lote posterior. Company NO lleva el campo: company_name es la
#   razón social y el branding lo cubre Letter Head.
#
# - Tab «Spain Compliance» en Company (spec 04 §2.1): hub de lo por-empresa.
#   Sección «General» con es_incidents_email — email externo de incidencias
#   (p. ej. asesor fiscal), TRANSVERSAL: lo consumen la caducidad de
#   certificados (capa AEAT, spec 13 §2) Y las incidencias de remisión de
#   VeriFactu (spec 04 §9). El lote de VeriFactu añadirá su sección dentro de
#   ESTE MISMO tab.

from __future__ import annotations

import frappe

TRADE_NAME_FIELD = {
	"fieldname": "es_trade_name",
	"label": "Nombre comercial",
	"fieldtype": "Data",
	"insert_after": "customer_name",
}

# Tab «Spain Compliance» en Company: tras el último tab del core (dashboard_tab
# — mismo punto de anclaje que usaba la referencia para su tab).
COMPANY_TAB_FIELD = {
	"fieldname": "es_tab",
	"label": "Spain Compliance",
	"fieldtype": "Tab Break",
	"insert_after": "dashboard_tab",
}

COMPANY_GENERAL_SECTION_FIELD = {
	"fieldname": "es_seccion_general",
	"label": "General",
	"fieldtype": "Section Break",
	"insert_after": "es_tab",
}

COMPANY_INCIDENTS_EMAIL_FIELD = {
	"fieldname": "es_incidents_email",
	"label": "Email de incidencias (compliance)",
	"fieldtype": "Data",
	"options": "Email",
	"insert_after": "es_seccion_general",
	"description": (
		"Email externo (p. ej. asesor fiscal) al que se notifican las incidencias"
		" de cumplimiento de la empresa: caducidad de certificados AEAT, rechazos"
		" y reintentos agotados de remisión, envíos estancados."
	),
}

CUSTOM_FIELDS = {
	"Customer": [TRADE_NAME_FIELD],
	"Supplier": [TRADE_NAME_FIELD | {"insert_after": "supplier_name"}],
	"Company": [
		COMPANY_TAB_FIELD,
		COMPANY_GENERAL_SECTION_FIELD,
		COMPANY_INCIDENTS_EMAIL_FIELD,
	],
}

# Campos propios de la app por doctype, para la limpieza simétrica de la
# desinstalación (doc 12 §12).
FIELDS_PER_DOCTYPE = {
	"Customer": ["es_trade_name"],
	"Supplier": ["es_trade_name"],
	"Company": ["es_tab", "es_seccion_general", "es_incidents_email"],
}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS)


def cleanup_custom_fields() -> None:
	"""Contrapartida de limpieza en before_uninstall (doc 12 §12).

	Guard de colisión: si algún campo nuestro existe en un doctype que NO
	declaramos (otra app), la desinstalación se detiene con remedio en lugar
	de borrar campos ajenos. (Un mismo fieldname puede existir legítimamente en
	varios doctypes NUESTROS, p. ej. es_trade_name en Customer/Supplier.)
	"""
	doctypes_by_field: dict[str, list[str]] = {}
	for doctype, fields in FIELDS_PER_DOCTYPE.items():
		for field in fields:
			doctypes_by_field.setdefault(field, []).append(doctype)

	for field, doctypes in doctypes_by_field.items():
		foreign = frappe.get_all(
			"Custom Field",
			filters={"fieldname": field, "dt": ("not in", doctypes)},
			pluck="name",
		)
		if foreign:
			frappe.throw(
				f"No se puede eliminar el Custom Field {field} de"
				f" {', '.join(doctypes)}: existe un campo con el mismo nombre en"
				" otro doctype (¿otra app?). Elimínelo a mano y reintente la"
				" desinstalación."
			)

	for doctype, fields in FIELDS_PER_DOCTYPE.items():
		frappe.db.delete("Custom Field", {"fieldname": ("in", fields), "dt": doctype})
