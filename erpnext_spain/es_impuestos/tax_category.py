# Categoría de impuestos por país (revisión del 31/10/2026).
#
# ERPNext elige la categoría de la factura de la dirección de facturación del
# tercero (Accounts Settings → «Determine Address Tax Category From») y, si no
# tiene, la del cliente o proveedor. La app la rellena por país:
#
# - España → «Nacional», salvo Canarias (códigos postales 35 y 38), Ceuta (51) y
#   Melilla (52) → «Canarias, Ceuta y Melilla».
# - País de la UE con NIF-IVA → «Entrega intracomunitaria» si es cliente y
#   «Adquisición intracomunitaria» si es proveedor; sin NIF (consumidor final), la
#   venta lleva IVA español → «Nacional».
# - Resto → «Extracomunitario».
#
# Se calcula al crear la dirección o el proveedor y se recalcula cuando cambian el
# país o el código postal, aunque se hubiera elegido otra categoría a mano: con el
# mismo país no se toca.
#
# «Nacional» se deja VACÍO (en la dirección y en el proveedor): vacío equivale a
# nacional. ERPNext solo aplica la plantilla de impuestos del artículo (p. ej. IVA
# 10 %) si su fila tiene la misma categoría que la factura, y las plantillas de los
# artículos no llevan categoría; con «Nacional» en el tercero, las ventas de IVA
# reducido saldrían al 21 %. Por lo mismo, no hay valor por defecto en clientes y
# proveedores. Vacía en la dirección, además, se respeta la del tercero (p. ej.
# «Nacional con recargo de equivalencia»).

import frappe
from frappe.model.document import Document

from erpnext_spain.es_impuestos.initial_data import (
	EXTRA_EU,
	INTRA_EU_PURCHASES,
	INTRA_EU_SALES,
	NATIONAL,
	SPECIAL_TERRITORIES,
)

CUSTOMER, SUPPLIER = "Customer", "Supplier"

SPAIN = "Spain"
SPECIAL_POSTCODES = ("35", "38", "51", "52")


def category_for(
	country: str | None, postcode: str | None = None, tax_id: str | None = None, side: str = CUSTOMER
) -> str | None:
	"""Categoría por país; NATIONAL para España peninsular y Baleares (y la UE sin
	NIF-IVA). Quien la guarda la convierte en vacío con `stored`."""
	if not country:
		return None
	if country == SPAIN:
		if (postcode or "").strip()[:2] in SPECIAL_POSTCODES:
			return SPECIAL_TERRITORIES
		return NATIONAL
	from erpnext_spain.es_efactura.codes import EU_COUNTRIES

	code = (frappe.get_cached_value("Country", country, "code") or "").upper()
	if code in EU_COUNTRIES:
		if not (tax_id or "").strip():
			return NATIONAL
		return INTRA_EU_PURCHASES if side == SUPPLIER else INTRA_EU_SALES
	return EXTRA_EU


def stored(category: str | None) -> str | None:
	"""Lo que se guarda en el campo: «Nacional» queda vacío (ver la cabecera)."""
	return None if category == NATIONAL else category


def _categories_ready() -> bool:
	"""Sin las categorías de la app (instalación a medias), comportamiento estándar."""
	return bool(frappe.db.exists("Tax Category", NATIONAL))


def _apply(doc: Document, category: str | None, fields: tuple[str, ...]) -> None:
	"""Nuevo: se rellena, salvo que ya traiga una categoría y el país sea nacional
	(se respeta, p. ej., «Nacional con recargo»). Existente: se recalcula si está
	vacío o si cambian el país o el código postal."""
	if not category:
		return
	if doc.is_new():
		if doc.get("tax_category") and category == NATIONAL:
			return
	elif doc.get("tax_category") and not any(doc.has_value_changed(field) for field in fields):
		return
	doc.tax_category = stored(category)


def _party(address: Document) -> tuple[str, str | None]:
	"""Lado (cliente o proveedor) y NIF del tercero de la dirección. Sin enlaces o
	con enlaces a los dos, se trata como de cliente."""
	sides = {
		link.link_doctype: link.link_name
		for link in address.get("links") or []
		if link.link_doctype in (CUSTOMER, SUPPLIER) and link.link_name
	}
	side = SUPPLIER if SUPPLIER in sides and CUSTOMER not in sides else CUSTOMER
	name = sides.get(side)
	return side, frappe.db.get_value(side, name, "tax_id") if name else None


def set_address_category(doc: Document, method: str | None = None) -> None:
	"""doc_event validate de Address."""
	if not doc.get("country") or not _categories_ready():
		return
	side, tax_id = _party(doc)
	_apply(doc, category_for(doc.country, doc.get("pincode"), tax_id, side), ("country", "pincode"))


def set_supplier_category(doc: Document, method: str | None = None) -> None:
	"""doc_event validate de Supplier: su propio país (por si no tiene dirección)."""
	if not doc.get("country") or not _categories_ready():
		return
	_apply(doc, category_for(doc.country, None, doc.get("tax_id"), SUPPLIER), ("country",))
