# Custom Fields de VeriFactu declarados en código Python (doc 12 §11), con
# limpieza en before_uninstall (doc 12 §12). Idempotentes: after_install +
# after_migrate (mismo wiring que nif/setup.py).
#
# - Sección «VeriFactu» NUEVA dentro del tab «Spain Compliance» de Company
#   (spec 04 §2.1): configuración por empresa. Los campos operativos dependen
#   (depends_on) del interruptor es_verifactu_enabled — mostrar/ocultar según
#   activación (patrón UX de la referencia, sin sus defectos).
# - Sección «VeriFactu» en Sales Invoice (spec 04 §2.3): tipo de factura,
#   snapshot de modo, estado denormalizado, rectificada externa y escape
#   hatches fiscales (clave de régimen L8A / causa de exención L10 — conjunto
#   básico extensible; la matriz completa es contrato del módulo 07, spec 04 §7).
#   El requerimiento condicional del tipo (company activa) lo aplica el
#   doc_event de emisión (lote 4): aquí se crean NO obligatorios.

from __future__ import annotations

import frappe

# --- Sección VeriFactu en el tab Spain Compliance de Company (spec 04 §2.1) ---

COMPANY_VERIFACTU_SECTION_FIELD = {
	"fieldname": "es_seccion_verifactu",
	"label": "VeriFactu",
	"fieldtype": "Section Break",
	# Tras la sección «Contabilidad y fiscalidad» del módulo base
	# (erpnext_spain/erpnext_spain/setup.py), que va antes de VeriFactu.
	"insert_after": "es_initial_data_version",
}

COMPANY_VERIFACTU_ENABLED_FIELD = {
	"fieldname": "es_verifactu_enabled",
	"label": "VeriFactu activado",
	"fieldtype": "Check",
	"insert_after": "es_seccion_verifactu",
	"description": (
		"Al activar se validan NIF, credencial AEAT, fecha de activación y series de"
		" la empresa. La desactivación no exige outbox vacío: los registros pendientes"
		" siguen remitiéndose (spec 04 §8)."
	),
}

COMPANY_VERIFACTU_TEST_MODE_FIELD = {
	"fieldname": "es_verifactu_test_mode",
	"label": "Modo operativo",
	"fieldtype": "Select",
	"options": "Pruebas\nProducción",
	"default": "Pruebas",
	"insert_after": "es_verifactu_enabled",
	"depends_on": "eval:doc.es_verifactu_enabled",
	"description": (
		"Pruebas: las remisiones van al entorno de pruebas de la AEAT y NO tienen"
		" validez fiscal. Producción: remisiones reales."
	),
}

COMPANY_VERIFACTU_ACTIVATION_DATE_FIELD = {
	"fieldname": "es_verifactu_activation_date",
	"label": "Fecha de activación",
	"fieldtype": "Date",
	"insert_after": "es_verifactu_test_mode",
	"depends_on": "eval:doc.es_verifactu_enabled",
	"description": (
		"Las facturas emitidas (FechaExpedicion) desde esta fecha generan registro"
		" VeriFactu; las anteriores son legado pre-VeriFactu. Se congela en cuanto"
		" la empresa tenga cualquier registro de facturación."
	),
}

COMPANY_VERIFACTU_REMISSION_MODE_FIELD = {
	"fieldname": "es_verifactu_remission_mode",
	"label": "Modalidad de remisión",
	"fieldtype": "Select",
	"options": "Inmediata\nDiferida",
	"default": "Diferida",
	"insert_after": "es_verifactu_activation_date",
	"depends_on": "eval:doc.es_verifactu_enabled",
	"description": (
		"Inmediata: envío encolado al emitir la factura. Diferida: drenaje por"
		" scheduler dentro de la ventana de remisión consecutiva."
	),
}

COMPANY_VERIFACTU_DRAFT_SERIES_FIELD = {
	"fieldname": "es_draft_series",
	"label": "Serie de borradores",
	"fieldtype": "Data",
	"insert_after": "es_verifactu_remission_mode",
	"depends_on": "eval:doc.es_verifactu_enabled",
	"description": (
		"Patrón de nombre temporal de los borradores (p. ej. «BORRADOR-.#####»):"
		" ningún número fiscal se consume hasta la emisión real (spec 04 §4). No"
		" debe colisionar con las series mapeadas."
	),
}

COMPANY_VERIFACTU_TIMEOUT_FIELD = {
	"fieldname": "es_verifactu_timeout_seconds",
	"label": "Timeout de remisión (segundos)",
	"fieldtype": "Int",
	"default": "60",
	"insert_after": "es_draft_series",
	"depends_on": "eval:doc.es_verifactu_enabled",
}

COMPANY_VERIFACTU_BATCH_LIMIT_FIELD = {
	"fieldname": "es_verifactu_batch_limit",
	"label": "Límite de lote de remisión",
	"fieldtype": "Int",
	"default": "1000",
	"insert_after": "es_verifactu_timeout_seconds",
	"depends_on": "eval:doc.es_verifactu_enabled",
	"description": "Máximo 1000 registros por envío (límite de la AEAT, spec 04 §8).",
}

COMPANY_VERIFACTU_IN_ORDER_CURE_FIELD = {
	"fieldname": "es_verifactu_mandatory_in_order_cure",
	"label": "Subsanación en orden obligatoria",
	"fieldtype": "Check",
	"insert_after": "es_verifactu_batch_limit",
	"depends_on": "eval:doc.es_verifactu_enabled",
	"description": (
		"Solo permite subsanar la factura cuyo último registro sea el más antiguo"
		" pendiente/erróneo del SIF (spec 04 §9)."
	),
}

COMPANY_VERIFACTU_NOI_FIELD = {
	"fieldname": "es_verifactu_noi",
	"label": "Número de instalación (NOI)",
	"fieldtype": "Data",
	"read_only": 1,
	"insert_after": "es_verifactu_mandatory_in_order_cure",
	"depends_on": "eval:doc.es_verifactu_enabled",
	"description": (
		"Identificador de la instalación ante la AEAT: derivado (SHA-256 Base32"
		" sobre site+empresa), persistido UNA vez al activar, inmutable."
	),
}

COMPANY_VERIFACTU_SERIES_FIELD = {
	"fieldname": "es_invoice_series",
	"label": "Series por tipo de factura",
	"fieldtype": "Table",
	"options": "ES Invoice Series",
	"insert_after": "es_verifactu_noi",
	"depends_on": "eval:doc.es_verifactu_enabled",
	"description": (
		"Biyección serie ↔ tipo de factura de ESTA empresa. Las series no se"
		" pueden compartir con otra empresa: el contador de series de ERPNext es"
		" global por prefijo."
	),
}

COMPANY_VERIFACTU_NOTIFICATION_ROLES_FIELD = {
	"fieldname": "es_verifactu_notification_roles",
	"label": "Roles con notificación de incidencias",
	"fieldtype": "Table",
	"options": "ES Verifactu Notification Role",
	"insert_after": "es_invoice_series",
	"depends_on": "eval:doc.es_verifactu_enabled",
	"description": (
		"Roles de usuarios que reciben in-app (Notification Log) las incidencias"
		" de compliance: rechazos AEAT, reintentos agotados, outbox estancado y"
		" caducidad de certificados (spec 04 §9)."
	),
}

COMPANY_FIELDS = [
	COMPANY_VERIFACTU_SECTION_FIELD,
	COMPANY_VERIFACTU_ENABLED_FIELD,
	COMPANY_VERIFACTU_TEST_MODE_FIELD,
	COMPANY_VERIFACTU_ACTIVATION_DATE_FIELD,
	COMPANY_VERIFACTU_REMISSION_MODE_FIELD,
	COMPANY_VERIFACTU_DRAFT_SERIES_FIELD,
	COMPANY_VERIFACTU_TIMEOUT_FIELD,
	COMPANY_VERIFACTU_BATCH_LIMIT_FIELD,
	COMPANY_VERIFACTU_IN_ORDER_CURE_FIELD,
	COMPANY_VERIFACTU_NOI_FIELD,
	COMPANY_VERIFACTU_SERIES_FIELD,
	COMPANY_VERIFACTU_NOTIFICATION_ROLES_FIELD,
]

# --- Sección VeriFactu en Sales Invoice (spec 04 §2.3) ---

SI_SECTION_FIELD = {
	"fieldname": "es_verifactu_seccion",
	"label": "VeriFactu",
	"fieldtype": "Section Break",
	# Primera sección de la pestaña «VeriFactu / SII» (es_facturacion/fiscal_tab.py).
	"insert_after": "es_fiscal_tab",
}

SI_INVOICE_TYPE_FIELD = {
	"fieldname": "es_invoice_type",
	"label": "Tipo de factura",
	"fieldtype": "Link",
	"options": "ES Invoice Type",
	"default": "F1",
	"insert_after": "es_verifactu_seccion",
	"in_list_view": 1,
	"description": (
		"F1 ordinaria · F2 simplificada · F3 sustitutiva de simplificadas · R1–R5"
		" rectificativas. La serie fiscal se toma del mapeo de la compañía."
		" Obligatorio al emitir si la compañía está activa (lo valida la emisión)."
	),
}

SI_MODE_FIELD = {
	"fieldname": "es_verifactu_mode",
	"label": "Modo operativo (snapshot)",
	"fieldtype": "Data",
	"read_only": 1,
	"insert_after": "es_invoice_type",
	"description": (
		"Snapshot inmutable del modo operativo al emitir (Verifactu / Verifactu en"
		" pruebas / Sin SIF): la anulación se gatea por él, no por el modo actual"
		" de la compañía (spec 04 §6)."
	),
}

SI_STATUS_FIELD = {
	"fieldname": "es_verifactu_status",
	"label": "Estado VeriFactu",
	"fieldtype": "Select",
	# Select (no Data): el valor es enumerable y el usuario lo filtra/lo ve
	# como píldora en el list view (el indicador vive en
	# public/js/sales_invoice_list.js#get_indicator). PRIMERA OPCIÓN VACÍA:
	# frappe rellena los Select SIN default con su primera opción al crear
	# docs (la factura aún no emitida lleva estado vacío, no «Pendiente
	# Envío» — la lección del E1 fantasma).
	"options": "\nPendiente Envío\nAlta Aceptada\nAlta Con Errores\nAnulada",
	"read_only": 1,
	"in_list_view": 1,
	"insert_after": "es_verifactu_mode",
	"description": (
		"Estado denormalizado del último registro, para listado y filtros; lo"
		" actualiza el procesador de respuestas de la AEAT."
	),
}

SI_EXT_RECT_NIF_FIELD = {
	"fieldname": "es_external_rectified_nif",
	"label": "NIF del emisor de la rectificada externa",
	"fieldtype": "Data",
	"insert_after": "es_verifactu_status",
	"description": "Para rectificar facturas emitidas fuera del sistema (sin enlace interno).",
}

SI_EXT_RECT_NUMBER_FIELD = {
	"fieldname": "es_external_rectified_number",
	"label": "Número de la rectificada externa",
	"fieldtype": "Data",
	"insert_after": "es_external_rectified_nif",
}

SI_EXT_RECT_DATE_FIELD = {
	"fieldname": "es_external_rectified_date",
	"label": "Fecha de la rectificada externa",
	"fieldtype": "Date",
	"insert_after": "es_external_rectified_number",
}

# Clave de régimen L8A — conjunto básico extensible (matriz completa: contrato
# del módulo de impuestos, spec 04 §7). Códigos verificados contra el catálogo
# oficial (ClaveRegimen del DetalleDesglose, Orden HAC/1177/2024).
SI_REGIME_KEY_FIELD = {
	"fieldname": "es_verifactu_regime_key",
	"label": "Clave de régimen",
	"fieldtype": "Select",
	"options": "01\n02\n03\n04\n05\n07\n11\n14\n15\n18\n19\n20",
	"default": "01",
	"insert_after": "es_external_rectified_date",
	"description": (
		"L8A: 01 general · 02 exportación · 03 bienes usados, arte y antigüedades ·"
		" 04 oro de inversión · 05 agencias de viajes · 07 criterio de caja ·"
		" 11 arrendamiento de local de negocio · 14 certificaciones de obra (AA."
		" PP.) · 15 tracto sucesivo · 18 recargo de equivalencia · 19 REAGYP ·"
		" 20 régimen simplificado."
	),
}

# Causa de exención L10 — conjunto básico extensible (E7/E8 existen en el XSD;
# sus etiquetas no están verificadas: se incorporarán con el contrato 07).
SI_EXEMPT_CAUSE_FIELD = {
	"fieldname": "es_verifactu_exempt_cause",
	"label": "Causa de exención",
	"fieldtype": "Select",
	# PRIMERA OPCIÓN VACÍA — OBLIGATORIA: frappe rellena los Select SIN
	# default con su PRIMERA opción al crear docs (get_static_default_value);
	# sin la línea vacía TODA factura nueva nacería con un E1 FANTASMA que
	# marca facturas tributadas como exentas (verificado en vivo: la regla
	# 1238 de la AEAT tira la tasa de las filas «exentas» → datos incoherentes
	# remitidos a la AEAT).
	"options": "\nE1\nE2\nE3\nE4\nE5\nE6",
	"insert_after": "es_verifactu_regime_key",
	"description": (
		"L10: E1 art. 20 LIVA (operaciones interiores exentas) · E2 art. 21"
		" (exportaciones) · E3 art. 22 (asimiladas a exportación) · E4 arts. 23 y"
		" 24 (regímenes aduaneros y fiscales) · E5 art. 25 (zonas francas y"
		" depósitos aduaneros) · E6 operación no sujeta."
	),
}

SALES_INVOICE_FIELDS = [
	SI_SECTION_FIELD,
	SI_INVOICE_TYPE_FIELD,
	SI_MODE_FIELD,
	SI_STATUS_FIELD,
	SI_EXT_RECT_NIF_FIELD,
	SI_EXT_RECT_NUMBER_FIELD,
	SI_EXT_RECT_DATE_FIELD,
	SI_REGIME_KEY_FIELD,
	SI_EXEMPT_CAUSE_FIELD,
]

CUSTOM_FIELDS = {
	"Company": COMPANY_FIELDS,
	"Sales Invoice": SALES_INVOICE_FIELDS,
}

# Campos propios de la app por doctype, para la limpieza simétrica de la
# desinstalación (doc 12 §12).
FIELDS_PER_DOCTYPE = {
	"Company": [field["fieldname"] for field in COMPANY_FIELDS],
	"Sales Invoice": [field["fieldname"] for field in SALES_INVOICE_FIELDS],
}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS)


def cleanup_custom_fields() -> None:
	"""Contrapartida de limpieza en before_uninstall (R3)."""
	from erpnext_spain.es_verifactu.printing import cleanup_printing
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	cleanup_printing()
	_cleanup(FIELDS_PER_DOCTYPE)
