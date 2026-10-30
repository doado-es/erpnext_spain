# Ciclo de instalación de ERPNext Spain (spec 01 §4).
#
# La app ya estaba instalada en el site cuando se añadió este wiring, por lo
# que la creación de Custom Fields, la siembra del catálogo y el materializado
# del Print Format de factura (lote 6a) van en BOTH after_install
# (instalaciones frescas) y after_migrate (idempotente, corre en cada
# migrate) — doc 12 §11.

from __future__ import annotations

import frappe

# Índices compuestos de rendimiento del renombre de emisión (spec 04 §4.3):
# rename_doc actualiza vínculos dinámicos POR NOMBRE en Version, File,
# Communication y Stock Ledger Entry (tablas de log/enlace SIN índice sobre
# esas columnas en el schema core). Precedente: erpnext gl_entry.py
# on_doctype_update. El renombre de GL Entry ya lo cubre ese precedente.
PERFORMANCE_INDEXES = [
	("Version", ["docname", "ref_doctype"]),
	("File", ["attached_to_name", "attached_to_doctype"]),
	# Communication usa reference_doctype (no reference_type) en v16.
	("Communication", ["reference_name", "reference_doctype"]),
	("Stock Ledger Entry", ["voucher_no", "voucher_type"]),
]


# Apps opcionales (R11): app → función que crea los custom fields que dependen
# de ella. Se ejecuta al instalar/migrar si la app ya está instalada y, vía
# after_app_install, si se instala después. Vacío hasta que una spec lo use
# (p. ej. HRMS).
OPTIONAL_APP_SETUP: dict[str, str] = {}

SPAIN = "Spain"


def after_install() -> None:
	setup_custom_fields()
	seed_catalogs()
	ensure_global_records()
	setup_printing()
	setup_optional_apps()
	warn_if_system_country_is_not_spain()


def after_migrate() -> None:
	setup_custom_fields()
	seed_catalogs()
	ensure_global_records()
	ensure_performance_indexes()
	setup_printing()
	setup_optional_apps()
	sync_report_templates()


def after_app_install(app_name: str) -> None:
	"""Hook de Frappe tras instalar cualquier app en el sitio (R11)."""
	if app_name in OPTIONAL_APP_SETUP:
		frappe.get_attr(OPTIONAL_APP_SETUP[app_name])()


def before_uninstall() -> None:
	# Orden inverso al de creación: VeriFactu y el módulo base cuelgan de la
	# pestaña que crea y limpia nif/setup.
	from erpnext_spain.erpnext_spain.setup import cleanup_custom_fields as _cleanup_base
	from erpnext_spain.es_impuestos.setup import cleanup_custom_fields as _cleanup_taxes
	from erpnext_spain.es_verifactu.setup import cleanup_custom_fields as _cleanup_verifactu
	from erpnext_spain.nif.setup import cleanup_custom_fields as _cleanup_nif

	_cleanup_taxes()
	_cleanup_verifactu()
	_cleanup_base()
	_cleanup_nif()


def setup_custom_fields() -> None:
	# El orden importa: la pestaña (nif) antes que sus secciones, y la sección
	# del módulo base antes que la de VeriFactu, que se inserta detrás.
	from erpnext_spain.erpnext_spain.setup import setup_custom_fields as _setup_base
	from erpnext_spain.es_impuestos.setup import setup_custom_fields as _setup_taxes
	from erpnext_spain.es_verifactu.setup import setup_custom_fields as _setup_verifactu
	from erpnext_spain.nif.setup import setup_custom_fields as _setup_nif

	_setup_nif()
	_setup_base()
	_setup_verifactu()
	_setup_taxes()


def setup_optional_apps() -> None:
	installed = set(frappe.get_installed_apps())
	for app_name, method in OPTIONAL_APP_SETUP.items():
		if app_name in installed:
			frappe.get_attr(method)()


def sync_report_templates() -> None:
	"""Inserta las Financial Report Template de las apps que aún no existan
	(spec 01 §4, spec 04). API pública de ERPNext v16; solo crea las que faltan,
	no modifica las existentes. Efecto lateral conocido: también vuelve a crear
	las plantillas estándar de ERPNext que un usuario haya borrado."""
	from erpnext.accounts.doctype.financial_report_template.financial_report_template import (
		sync_financial_report_templates,
	)

	sync_financial_report_templates()


def warn_if_system_country_is_not_spain() -> None:
	"""Requisito de instalación (spec 01): algunos regional overrides de ERPNext
	se resuelven por el país del sistema cuando ERPNext no fija la compañía
	(spec 06 §3). Solo avisa; no bloquea la instalación."""
	country = frappe.db.get_single_value("System Settings", "country")
	if country == SPAIN:
		return
	if not country:
		message = (
			"ERPNext Spain: el país del sistema aún no está configurado. Elija España"
			" en el asistente de configuración (o en System Settings → Country);"
			" algunas funciones fiscales solo se ejecutan con país España."
		)
	else:
		message = (
			f"ERPNext Spain: el país del sistema es «{country}». Cámbielo a España en"
			" System Settings → Country; algunas funciones fiscales (p. ej. los"
			" asientos de autorrepercusión del IVA) solo se ejecutan con país España."
		)
	print(message)


def setup_printing() -> None:
	from erpnext_spain.es_verifactu.printing import setup_printing as _setup_printing

	_setup_printing()


def ensure_global_records() -> None:
	"""Registros globales de los datos iniciales (spec 09 §2)."""
	from erpnext_spain.es_impuestos.initial_data import ensure_global_records as _ensure_taxes

	_ensure_taxes()


def seed_catalogs() -> None:
	from erpnext_spain.es_verifactu.catalog import seed_invoice_types

	seed_invoice_types()


def ensure_performance_indexes() -> None:
	"""Índices compuestos del renombre (spec 04 §4.3). Idempotente:
	frappe.db.add_index valida con has_index por nombre y emite ADD INDEX
	IF NOT EXISTS (mariadb/database.py) — corre en cada migrate sin
	duplicar nada. El commit interno de add_index es el mismo patrón del
	on_doctype_update de erpnext durante migrate."""
	for doctype, fields in PERFORMANCE_INDEXES:
		frappe.db.add_index(doctype, fields)
