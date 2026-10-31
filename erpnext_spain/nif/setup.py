# Custom Fields declarados en código Python (doc 12 §11), con limpieza en
# before_uninstall (doc 12 §12). Idempotentes: after_install + after_migrate.
#
# - es_trade_name (spec 14): nombre comercial/marca del tercero, transversal
#   (es_, no es_verifactu_). Solo display — lo consumirán print formats vía
#   jinja en un lote posterior. Company no lleva nombre comercial; lleva la
#   razón social (es_legal_name, por defecto el nombre de la compañía), que es
#   la que va a la AEAT, a Facturae y a los ficheros bancarios.
#
# - Tab «Spain Compliance» en Company (spec 04 §2.1): hub de lo por-empresa.
#   Sección «General» con es_incidents_email — email externo de incidencias
#   (p. ej. asesor fiscal), TRANSVERSAL: lo consumen la caducidad de
#   certificados (capa AEAT, spec 13 §2) Y las incidencias de remisión de
#   VeriFactu (spec 04 §9). El lote de VeriFactu añadirá su sección dentro de
#   ESTE MISMO tab.

from __future__ import annotations

import frappe

from erpnext_spain.nif.aeat_census import party_fields

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

COMPANY_LEGAL_NAME_FIELD = {
	"fieldname": "es_legal_name",
	"label": "Razón social",
	"fieldtype": "Data",
	"insert_after": "es_seccion_general",
	"description": (
		"Nombre fiscal de la empresa tal como figura en el censo de la AEAT (p. ej. «EMPRESA"
		" EJEMPLO SL»). Se usa en VeriFactu, el SII, Facturae, los modelos y los ficheros"
		" bancarios. Si se deja vacío, toma el nombre de la compañía."
	),
}

COMPANY_INCIDENTS_EMAIL_FIELD = {
	"fieldname": "es_incidents_email",
	"label": "Email de incidencias (compliance)",
	"fieldtype": "Data",
	"options": "Email",
	"insert_after": "es_legal_name",
	"description": (
		"Email externo (p. ej. asesor fiscal) al que se notifican las incidencias"
		" de cumplimiento de la empresa: caducidad de certificados AEAT, rechazos"
		" y reintentos agotados de remisión, envíos estancados."
	),
}


# Resultado de la comprobación del NIF o del NIF-IVA en VIES (spec 15, F4).
def vies_fields(insert_after: str) -> list[dict]:
	return [
		{
			"fieldname": "es_vies_status",
			"label": "Comprobación del NIF",
			"fieldtype": "Data",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": insert_after,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "es_vies_name",
			"label": "Nombre registrado en VIES",
			"fieldtype": "Data",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "es_vies_status",
		},
		{
			"fieldname": "es_vies_checked_on",
			"label": "Fecha de la comprobación",
			"fieldtype": "Datetime",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "es_vies_name",
		},
	]


CUSTOM_FIELDS = {
	"Customer": [TRADE_NAME_FIELD, *vies_fields("tax_id"), *party_fields("es_vies_checked_on")],
	"Supplier": [
		TRADE_NAME_FIELD | {"insert_after": "supplier_name"},
		*vies_fields("tax_id"),
		*party_fields("es_vies_checked_on"),
	],
	"Company": [
		COMPANY_TAB_FIELD,
		COMPANY_GENERAL_SECTION_FIELD,
		COMPANY_LEGAL_NAME_FIELD,
		COMPANY_INCIDENTS_EMAIL_FIELD,
	],
}

# Campos propios de la app por doctype, para la limpieza simétrica de la
# desinstalación (doc 12 §12).
FIELDS_PER_DOCTYPE = {
	doctype: [field["fieldname"] for field in fields] for doctype, fields in CUSTOM_FIELDS.items()
}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from erpnext_spain.utils.company import fill_missing_legal_names

	create_custom_fields(CUSTOM_FIELDS, update=True)
	fill_missing_legal_names()


def cleanup_custom_fields() -> None:
	"""Contrapartida de limpieza en before_uninstall (R3)."""
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	_cleanup(FIELDS_PER_DOCTYPE)
