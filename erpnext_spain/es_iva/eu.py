# Estados de la UE por país de ERPNext (para la clave de identificación del
# tercero). Reutiliza la lista de prefijos de Facturae (es_efactura/codes.py).

import frappe

from erpnext_spain.es_efactura.codes import EU_COUNTRIES

# Prefijo del NIF-IVA distinto del código ISO del país.
VAT_PREFIX_TO_ISO = {"EL": "GR"}


def is_eu_country(country: str | None) -> bool:
	if not country:
		return False
	code = (frappe.get_cached_value("Country", country, "code") or "").upper()
	return code in EU_COUNTRIES


def country_from_vat_id(tax_id: str | None) -> str | None:
	"""País de un NIF-IVA europeo por su prefijo (p. ej. «FR123…» → France)."""
	prefix = (tax_id or "")[:2].upper()
	if not prefix.isalpha() or prefix == "ES" or prefix not in EU_COUNTRIES:
		return None
	return frappe.db.get_value("Country", {"code": VAT_PREFIX_TO_ISO.get(prefix, prefix).lower()}, "name")
