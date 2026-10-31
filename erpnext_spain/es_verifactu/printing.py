# Print Format «Factura España VeriFactu» + Property Setter del formato por
# defecto — lote 6a (spec 04 §11, doc 12 §13).
#
# El formato vive en `print/factura_espana_verifactu.html` y se materializa
# como registro Print Format (Jinja, custom) en cada migrate: si ya existe se
# ACTUALIZA el HTML — el archivo es la fuente de verdad del código, la BD la
# copia servida a las plantillas (así los cambios de formato propagan con el
# migrate, sin fixture JSON).
#
# El default_print_format de Sales Invoice se fija con
# frappe.make_property_setter (doc 12 §13): is_system_generated=False (creado
# por la app, no por el framework — afecta a cómo lo tratan las
# actualizaciones) y validate_fields_for_doctype=False (no revalida el
# schema del doctype core).
#
# Idempotencia (after_migrate corre en CADA migrate):
# - El formato se re-crea/actualiza por NOMBRE (upsert).
# - El Property Setter tiene autoname determinista
#   («Sales Invoice-main-default_print_format») y su validate BORRA el
#   anterior antes de insertar (property_setter.py:42): re-crearlo no
#   duplica. Aun así se salta cuando ya existe con NUESTRO valor (guard
#   barato: ni siquiera toca la caché del doctype si no hay cambio).

from __future__ import annotations

import os

import frappe

FORMAT_NAME = "Factura España VeriFactu"
INVOICE_DOCTYPE = "Sales Invoice"

# Campos del registro Print Format: Jinja custom completo (HTML propio, sin
# builder), estándar de la app (no editable como «Custom» del usuario).
FORMAT_FIELDS = {
	"doc_type": INVOICE_DOCTYPE,
	"module": "ES Verifactu",
	"print_format_type": "Jinja",
	"custom_format": 1,
	"standard": "Yes",
	"default_print_language": "es",
	"pdf_generator": "wkhtmltopdf",
	"font_size": 13,
}


def setup_printing() -> None:
	"""Crea/actualiza el formato y fija el default_print_format. Idempotente."""
	_ensure_print_format()
	_set_default_format()


def _ensure_print_format() -> str:
	"""Upsert del Print Format desde el HTML de `print/`. Devuelve el nombre.

	Print Format nombra por PROMPT: el docname se fija explícitamente (sin
	nombre el insert rebota con «Please set the document name»)."""
	if frappe.db.exists("Print Format", FORMAT_NAME):
		format_doc = frappe.get_doc("Print Format", FORMAT_NAME)
	else:
		format_doc = frappe.new_doc("Print Format")
		format_doc.update(FORMAT_FIELDS)
		format_doc.name = FORMAT_NAME

	format_doc.html = _read_html()
	format_doc.save(ignore_permissions=True)
	return format_doc.name


def _set_default_format() -> None:
	"""default_print_format de Sales Invoice → nuestro formato (doc 12 §13)."""
	existing = frappe.db.get_value(
		"Property Setter",
		{"doc_type": INVOICE_DOCTYPE, "property": "default_print_format"},
		"value",
	)
	if existing == FORMAT_NAME:
		return

	frappe.make_property_setter(
		{
			"doctype": INVOICE_DOCTYPE,
			"doctype_or_field": "DocType",
			"fieldname": "",
			"property": "default_print_format",
			"value": FORMAT_NAME,
			"property_type": "Data",
		},
		validate_fields_for_doctype=False,
		is_system_generated=False,
	)


def cleanup_printing() -> None:
	"""Contrapartida de `setup_printing` en before_uninstall (H5).

	Frappe borra el Print Format con el módulo de la app, pero no el Property
	Setter que lo fija como predeterminado: Sales Invoice quedaría apuntando a
	un formato inexistente. Solo se borra si sigue apuntando a nuestro formato
	(si el usuario eligió otro, se respeta)."""
	for name in frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": INVOICE_DOCTYPE,
			"property": "default_print_format",
			"value": FORMAT_NAME,
		},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype=INVOICE_DOCTYPE)


def _read_html() -> str:
	path = os.path.join(
		frappe.get_app_path("erpnext_spain"), "es_verifactu", "print", "factura_espana_verifactu.html"
	)
	with open(path, encoding="utf-8") as html_file:
		return html_file.read()
