# Utilidades de los ficheros de la AEAT para las declaraciones informativas
# (registros de 500 posiciones: tipo 1 = declarante, tipo 2 = declarados).
#
# Reglas comunes de los diseños de registro: ISO-8859-1; alfanuméricos en
# mayúsculas, sin acentos (se admiten Ñ y Ç), alineados a la izquierda con
# blancos; numéricos alineados a la derecha con ceros; importes en céntimos sin
# separador; los negativos llevan «N» en la posición de signo.

import re
import unicodedata

import frappe
from frappe.utils import flt

from erpnext_spain.es_modelos.returns import identification, page

RECORD_LENGTH = 500
KEEP = {"Ñ", "Ç"}


def an(value, length: int, extra: str = "") -> str:
	"""Alfanumérico: mayúsculas, sin acentos ni signos raros, a la izquierda.
	`extra`: caracteres que el campo admite además (p. ej. «@_» en un correo)."""
	text = []
	for char in str(value or "").upper():
		if char in KEEP or char in extra:
			text.append(char)
			continue
		base = unicodedata.normalize("NFD", char)[0]
		text.append(base if re.match(r"[A-Z0-9 ,.\-&/'()]", base) else " ")
	return re.sub(r"\s+", " ", "".join(text)).strip()[:length].ljust(length)


def num(value, length: int) -> str:
	return str(int(flt(value))).rjust(length, "0")[-length:]


def cents(value, length: int) -> str:
	"""Importe sin signo en céntimos."""
	return str(round(abs(flt(value)) * 100)).rjust(length, "0")[-length:]


def signed_cents(value, length: int) -> str:
	"""Signo («N» o blanco) seguido del importe en céntimos: `length` incluye el signo."""
	return ("N" if flt(value) < 0 else " ") + cents(value, length - 1)


def nif(tax_id) -> str:
	"""NIF español de 9 posiciones, alineado a la derecha con ceros."""
	value = re.sub(r"[^0-9A-Za-z]", "", tax_id or "").upper()
	if value.startswith("ES") and len(value) == 11:
		value = value[2:]
	return value[-9:].rjust(9, "0") if value else " " * 9


def vat_number(tax_id) -> tuple[str, str]:
	"""NIF-IVA europeo: (código de país, número)."""
	value = re.sub(r"[^0-9A-Za-z]", "", tax_id or "").upper()
	return value[:2], value[2:]


def province_code(party_type: str, party: str) -> str:
	"""Provincia del domicilio: los dos primeros dígitos del código postal español."""
	addresses = frappe.get_all(
		"Address",
		filters=[
			["Dynamic Link", "link_doctype", "=", party_type],
			["Dynamic Link", "link_name", "=", party],
			["Address", "country", "=", "Spain"],
		],
		fields=["pincode", "is_primary_address", "address_type"],
		order_by="is_primary_address desc, creation",
	)
	for address in addresses:
		digits = re.sub(r"\D", "", address.pincode or "")
		if len(digits) == 5 and 1 <= int(digits[:2]) <= 52:
			return digits[:2]
	return ""


def record(fields: list[tuple[int, str]]) -> str:
	return page(RECORD_LENGTH, fields)


def declarant_head(doc, model: str, record_type: str = "1") -> list[tuple[int, str]]:
	"""Posiciones 1-17, comunes a los registros de tipo 1 y 2."""
	company_nif, _name = identification(doc)
	return [(1, record_type), (2, model), (5, str(doc.fiscal_year)), (9, nif(company_nif))]


def declarant_record(doc, model: str, support: str | None = "T") -> list[tuple[int, str]]:
	"""Posiciones 1-135 del registro de tipo 1 (iguales en 180, 190, 347 y 349)."""
	_nif, name = identification(doc)
	return [
		*declarant_head(doc, model),
		(18, an(name, 40)),
		*([(58, support)] if support else []),
		(59, num(re.sub(r"\D", "", doc.contact_phone or ""), 9)),
		(68, an(doc.contact_name, 40)),
		(108, num(doc.declaration_number, 13)),
		(121, "C" if doc.replacement == "Complementaria" else " "),
		(122, "S" if doc.replacement == "Sustitutiva" else " "),
		(123, num(re.sub(r"\D", "", doc.previous_declaration or ""), 13)),
	]


def as_file(records: list[str]) -> str:
	return "\r\n".join(records) + "\r\n"


def withholding_entries(company: str, start, end, tax_model: str) -> list:
	"""Retenciones practicadas (Tax Withholding Entry) del periodo para un modelo (111 o 115)."""
	entry = frappe.qb.DocType("Tax Withholding Entry")
	category = frappe.qb.DocType("Tax Withholding Category")
	return (
		frappe.qb.from_(entry)
		.join(category)
		.on(category.name == entry.tax_withholding_category)
		.select(
			entry.party_type,
			entry.party,
			entry.tax_id,
			entry.tax_rate,
			entry.taxable_amount,
			entry.withholding_amount,
			entry.taxable_doctype,
			entry.taxable_name,
			entry.withholding_date,
			category.name.as_("category"),
			category.es_key_190.as_("key_190"),
			category.es_subkey_190.as_("subkey_190"),
		)
		.where(entry.company == company)
		.where(entry.docstatus == 1)
		.where(entry.status.notin(["Cancelled", "Duplicate"]))
		.where(entry.withholding_amount != 0)
		.where(category.es_tax_model == tax_model)
		.where(entry.withholding_date[start:end])
		.orderby(entry.party)
	).run(as_dict=True)
