# Utilidades para los custom fields de la app (maestro R3): se crean por
# código en after_install/after_migrate y se borran en before_uninstall.

from __future__ import annotations

import frappe


def cleanup_custom_fields(fields_per_doctype: dict[str, list[str]]) -> None:
	"""Borra los custom fields propios declarados en ``fields_per_doctype``.

	Guarda de colisión: si un fieldname nuestro existe también en un doctype que
	NO declaramos (otra app), la desinstalación se detiene con el remedio en
	lugar de borrar campos ajenos. Un mismo fieldname puede existir
	legítimamente en varios doctypes nuestros (p. ej. es_trade_name en Customer
	y Supplier)."""
	doctypes_by_field: dict[str, list[str]] = {}
	for doctype, fields in fields_per_doctype.items():
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

	for doctype, fields in fields_per_doctype.items():
		frappe.db.delete("Custom Field", {"fieldname": ("in", fields), "dt": doctype})
