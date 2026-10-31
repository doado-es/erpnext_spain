# Catálogo de tipos de factura VeriFactu (spec 04 §2.1) — código idempotente,
# NO fixtures JSON (doc 12 §11).
#
# Semántica VERIFICADA contra el XSD oficial de la AEAT (SuministroInformacion.xsd
# del entorno de pruebas, Orden HAC/1177/2024 — anotaciones del propio esquema):
#   F1: factura (art. 6, 7.2 y 7.3 RD 1619/2012)
#   F2: factura simplificada (y facturas sin identificación del destinatario, art. 6.1.d)
#   F3: factura emitida en sustitución de facturas simplificadas facturadas y declaradas
#   R1: rectificativa (art. 80.1 y 80.2 LIVA y error fundado en derecho)
#   R2: rectificativa (art. 80.3 LIVA)
#   R3: rectificativa (art. 80.4 LIVA)
#   R4: rectificativa (resto de causas)
#   R5: rectificativa EN FACTURAS SIMPLIFICADAS
#
# is_simplified: F2 (simplificada) y R5 (rectificativa de simplificadas). El
# XSD sitúa el «resto» (R4) sobre facturas ordinarias — la rectificativa de
# simplificadas es R5.
#
# rectification_type: el XSD define S (sustitutiva) / I (incremental, por
# diferencias). Por defecto «I» en todas las R* — el mismo criterio que la
# referencia derivaba para R1/R4/R5, coherente con los flujos rectificativos
# por diferencias de ERPNext (return_against). El lote de emisión (spec 04 §6)
# lo refina cuando la rectificación es por sustitución.

from __future__ import annotations

import frappe

DOCTYPE = "ES Invoice Type"

INVOICE_TYPE_CATALOG = (
	{"code": "F1", "label": "Factura (ordinaria)", "is_simplified": 0, "rectification_type": ""},
	{"code": "F2", "label": "Factura simplificada", "is_simplified": 1, "rectification_type": ""},
	{
		"code": "F3",
		"label": "Factura en sustitución de facturas simplificadas",
		"is_simplified": 0,
		"rectification_type": "",
	},
	{
		"code": "R1",
		"label": "Rectificativa (art. 80.1 y 80.2 LIVA y error fundado en derecho)",
		"is_simplified": 0,
		"rectification_type": "I",
	},
	{"code": "R2", "label": "Rectificativa (art. 80.3 LIVA)", "is_simplified": 0, "rectification_type": "I"},
	{"code": "R3", "label": "Rectificativa (art. 80.4 LIVA)", "is_simplified": 0, "rectification_type": "I"},
	{"code": "R4", "label": "Rectificativa (resto de causas)", "is_simplified": 0, "rectification_type": "I"},
	{
		"code": "R5",
		"label": "Rectificativa de facturas simplificadas",
		"is_simplified": 1,
		"rectification_type": "I",
	},
)

SYNCED_FIELDS = ("label", "is_simplified", "rectification_type")


def seed_invoice_types() -> None:
	"""Siembra/sincroniza el catálogo completo, idempotente (after_install +
	after_migrate). La sincronización de etiquetas/semántica permite corregir
	el catálogo en un migrate si el catálogo oficial cambia; el docname (= el
	código) es estable."""
	for entry in INVOICE_TYPE_CATALOG:
		if not frappe.db.exists(DOCTYPE, entry["code"]):
			frappe.get_doc({"doctype": DOCTYPE, **entry}).insert(ignore_permissions=True)
			continue

		current = frappe.db.get_value(DOCTYPE, entry["code"], SYNCED_FIELDS, as_dict=True)
		if _differs(current, entry):
			frappe.db.set_value(
				DOCTYPE,
				entry["code"],
				{field: entry[field] for field in SYNCED_FIELDS},
				update_modified=False,
			)


def _differs(current, entry: dict) -> bool:
	return any((getattr(current, field) or "") != entry[field] for field in SYNCED_FIELDS)
