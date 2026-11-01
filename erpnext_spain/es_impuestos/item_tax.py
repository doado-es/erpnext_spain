# Plantillas de impuestos de artículo por categoría (revisión del 31/10/2026).
#
# ERPNext aplica la plantilla de impuestos de un artículo o de su grupo (p. ej.
# «IVA 10 %») solo si la fila tiene EXACTAMENTE la misma categoría de impuestos que
# la factura; una fila sin categoría solo vale para facturas sin categoría
# (erpnext/stock/get_item_details._get_item_tax_template). Sin más, un cliente con
# recargo de equivalencia o con retención, o una compra intracomunitaria, llevarían
# el tipo general aunque el artículo tenga tipo reducido.
#
# Por cada fila sin categoría, la app añade la misma plantilla (con su vigencia y
# sus importes) para las categorías en las que el tipo del artículo también vale:
# recargo de equivalencia, retención y adquisición intracomunitaria (la plantilla
# del artículo ya trae el recargo y la autorrepercusión al mismo tipo). No se
# añade para la entrega intracomunitaria ni la exportación: van exentas y la
# plantilla les pondría el IVA. Solo añade filas, nunca borra. Solo se replican las
# plantillas de compañías con el plan PGC aplicado (R7).

import frappe
from frappe.model.document import Document

from erpnext_spain.es_impuestos.initial_data import INTRA_EU_PURCHASES, NATIONAL_RE, NATIONAL_WITHHOLDING

MIRRORED_CATEGORIES = (NATIONAL_RE, NATIONAL_WITHHOLDING, INTRA_EU_PURCHASES)
PARENTS = ("Item", "Item Group")
KEY_FIELDS = ("item_tax_template", "valid_from", "minimum_net_rate", "maximum_net_rate")


def _key(row) -> tuple:
	return tuple(row.get(field) or None for field in KEY_FIELDS)


def mirror_rows(doc: Document, method: str | None = None) -> bool:
	"""doc_event validate de Item e Item Group. Devuelve si ha añadido filas."""
	from erpnext_spain.utils.gating import is_pgc_company

	rows = doc.get("taxes") or []
	blank = [
		row
		for row in rows
		if not row.get("tax_category")
		and row.get("item_tax_template")
		and is_pgc_company(frappe.get_cached_value("Item Tax Template", row.item_tax_template, "company"))
	]
	if not blank:
		return False
	categories = [c for c in MIRRORED_CATEGORIES if frappe.get_cached_value("Tax Category", c, "name")]
	present = {(_key(row), row.get("tax_category") or "") for row in rows}
	added = False
	for row in blank:
		for category in categories:
			if (_key(row), category) in present:
				continue
			doc.append("taxes", {**{field: row.get(field) for field in KEY_FIELDS}, "tax_category": category})
			present.add((_key(row), category))
			added = True
	return added


def mirror_existing() -> int:
	"""Artículos y grupos que ya existían: se completan una vez (patch)."""
	changed = 0
	for parenttype in PARENTS:
		parents = frappe.get_all(
			"Item Tax",
			filters={"parenttype": parenttype, "parentfield": "taxes"},
			or_filters=[["tax_category", "is", "not set"], ["tax_category", "=", ""]],
			pluck="parent",
			distinct=True,
		)
		for name in parents:
			doc = frappe.get_doc(parenttype, name)
			if mirror_rows(doc):
				doc.flags.ignore_permissions = True
				doc.save()
				changed += 1
	return changed
