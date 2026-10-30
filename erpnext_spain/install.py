# Instalación/desinstalación de Spain Compliance.
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


def after_install() -> None:
	setup_custom_fields()
	seed_catalogs()
	setup_printing()


def after_migrate() -> None:
	setup_custom_fields()
	seed_catalogs()
	ensure_performance_indexes()
	setup_printing()


def before_uninstall() -> None:
	# VeriFactu primero: sus campos viven bajo el tab que limpia nif/setup.
	from erpnext_spain.es_verifactu.setup import cleanup_custom_fields

	cleanup_custom_fields()

	from erpnext_spain.nif.setup import cleanup_custom_fields as _cleanup_nif

	_cleanup_nif()


def setup_custom_fields() -> None:
	from erpnext_spain.nif.setup import setup_custom_fields as _setup_nif
	from erpnext_spain.es_verifactu.setup import setup_custom_fields as _setup_verifactu

	_setup_nif()
	_setup_verifactu()


def setup_printing() -> None:
	from erpnext_spain.es_verifactu.printing import setup_printing as _setup_printing

	_setup_printing()


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
