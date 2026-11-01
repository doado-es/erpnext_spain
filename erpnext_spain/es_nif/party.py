# doc_events de Customer/Supplier/Company (spec 14 §2).
#
# Regla de terceros (Customer/Supplier): si tax_id está presente Y (patrón
# español O tercero español por su dirección/país) → validar. NIF ausente no
# bloquea (se captura en la compuerta de la factura).
#
# Regla de Company: NIF presente Y (país España O patrón español) → validar,
# SIEMPRE bloqueante — el NIF del emisor es el más crítico del sistema
# (recomendación spec 14 §Dudas abiertas).

from __future__ import annotations

import frappe
from frappe.contacts.doctype.address.address import get_default_address
from frappe.model.document import Document

from erpnext_spain.es_nif import validator

MODE_BLOCK = "Bloquear"
MODE_WARN = "Solo avisar"

THIRD_PARTIES = ("Customer", "Supplier")


def validate(doc: Document, method: str | None = None) -> None:
	if doc.doctype == "Company":
		_validate_company(doc)
	else:
		_validate_party(doc)


def _validate_party(doc: Document) -> None:
	tax_id = (doc.get("tax_id") or "").strip()
	if not tax_id:
		return

	if not validator.looks_spanish(tax_id) and not _is_spanish(doc):
		return

	try:
		result = validator.validate_spanish_tax_id(tax_id)
	except validator.InvalidTaxID as exc:
		if _validation_mode() == MODE_WARN:
			frappe.msgprint(
				title="Aviso de NIF (modo «Solo avisar»)",
				msg=f"El NIF {tax_id} no es válido. {exc}"
				" Corrija la ficha del tercero, o cambie el modo de validación en ES Settings.",
				indicator="orange",
			)
			return
		frappe.throw(str(exc), title="NIF no válido")
	_warn_type_mismatch(doc, result.kind)


TYPE_FIELDS = {
	"Customer": ("customer_type", "Tipo de cliente"),
	"Supplier": ("supplier_type", "Tipo de proveedor"),
}
INDIVIDUAL = "Individual"


def _warn_type_mismatch(doc: Document, kind: str) -> None:
	"""El tipo de cliente o de proveedor de ERPNext no cuadra con el NIF (p. ej. un DNI
	con el tipo por defecto «Company»). No bloquea: los envíos a la AEAT y Facturae
	usan el NIF."""
	field, label = TYPE_FIELDS.get(doc.doctype, (None, None))
	if not field or not doc.get(field):
		return
	individual_nif = kind in ("dni", "nie")
	if individual_nif == (doc.get(field) == INDIVIDUAL):
		return
	expected = INDIVIDUAL if individual_nif else "Company"
	who = "una persona física" if individual_nif else "una persona jurídica"
	frappe.msgprint(
		f"El NIF {doc.tax_id} es de {who}, pero el campo «{label}» es «{doc.get(field)}»."
		f" Remedio: cámbielo a «{expected}».",
		title="Tipo de tercero",
		indicator="orange",
	)


def _validate_company(doc: Document) -> None:
	tax_id = (doc.get("tax_id") or "").strip()
	if not tax_id:
		return

	if (doc.get("country") or "") != "Spain" and not validator.looks_spanish(tax_id):
		return

	try:
		validator.validate_spanish_tax_id(tax_id)
	except validator.InvalidTaxID as exc:
		frappe.throw(str(exc), title="NIF no válido")


def _is_spanish(doc: Document) -> bool:
	country = doc.get("country")
	if not country and doc.doctype in THIRD_PARTIES and doc.name:
		country = _primary_address_country(doc.doctype, doc.name)
	return country == "Spain"


def _primary_address_country(doctype: str, name: str) -> str | None:
	address = get_default_address(doctype, name)
	if not address:
		return None
	return frappe.db.get_value("Address", address, "country")


def _validation_mode() -> str:
	return frappe.db.get_single_value("ES Settings", "modo_validacion_nif") or MODE_BLOCK
