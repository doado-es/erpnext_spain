# Utilidades SEPA (spec 11 §2): IBAN, identificador de acreedor y dirección
# estructurada de los terceros.

import re

import frappe
from frappe import _
from stdnum import iban as stdnum_iban

# Desde el 22/11/2026 la EPC solo admite direcciones estructuradas o híbridas
# (país y municipio obligatorios; hasta dos líneas de dirección libres).
STRUCTURED_ADDRESS_FROM = "2026-11-22"

SEPA_TEXT = re.compile(r"[^A-Za-z0-9/\-?:().,'+ ]")
SPANISH_CHARS = str.maketrans(
	"ÁÉÍÓÚÀÈÌÒÙÄËÏÖÜÂÊÎÔÛÑÇáéíóúàèìòùäëïöüâêîôûñç", "AEIOUAEIOUAEIOUAEIOUNCaeiouaeiouaeiouaeiounc"
)


def sepa_text(value: str | None, length: int) -> str:
	"""Texto con el juego de caracteres latino básico de la EPC."""
	text = (value or "").translate(SPANISH_CHARS)
	return SEPA_TEXT.sub(" ", text).strip()[:length]


def clean_iban(value: str | None) -> str:
	return re.sub(r"\s", "", value or "").upper()


def is_valid_iban(value: str | None) -> bool:
	return bool(value) and stdnum_iban.is_valid(clean_iban(value))


def creditor_identifier(nif: str, suffix: str = "000", country: str = "ES") -> str:
	"""Identificador de acreedor SEPA (AT-02): país + dígitos de control + sufijo
	de 3 caracteres + NIF. Los dígitos de control (ISO 7064 MOD 97-10) se calculan
	sobre el NIF seguido del país y «00», sin el sufijo."""
	national = re.sub(r"[^0-9A-Z]", "", (nif or "").upper())
	if national.startswith(country):
		national = national[len(country) :]
	digits = "".join(str(int(char, 36)) for char in f"{national}{country}00")
	check = 98 - int(digits) % 97
	return f"{country}{check:02d}{(suffix or '000')[:3].upper():0>3}{national}"


def party_address(party_type: str, party: str) -> dict | None:
	"""Dirección principal del tercero (o la primera enlazada)."""
	field = "supplier_primary_address" if party_type == "Supplier" else "customer_primary_address"
	name = frappe.get_cached_value(party_type, party, field)
	if not name:
		links = frappe.get_all(
			"Dynamic Link",
			filters={"link_doctype": party_type, "link_name": party, "parenttype": "Address"},
			pluck="parent",
			limit=1,
		)
		name = links[0] if links else None
	if not name:
		return None
	return frappe.get_cached_value(
		"Address", name, ["address_line1", "address_line2", "pincode", "city", "country"], as_dict=True
	)


def country_code(country: str | None) -> str:
	return (frappe.get_cached_value("Country", country, "code") or "").upper() if country else ""


def address_problem(address: dict | None) -> str | None:
	"""Motivo por el que la dirección no es estructurada/híbrida, o None."""
	if not address:
		return _("sin dirección")
	missing = [
		label for field, label in (("city", _("municipio")), ("country", _("país"))) if not address.get(field)
	]
	return _("faltan {0}").format(", ".join(missing)) if missing else None


def check_parties(parties: list[tuple[str, str]]) -> None:
	"""Bloquea la generación si algún tercero no tiene dirección estructurada."""
	problems = []
	for party_type, party in dict.fromkeys(parties):
		problem = address_problem(party_address(party_type, party))
		if problem:
			problems.append(f"{party} ({problem})")
	if problems:
		frappe.throw(
			_(
				"Desde el 22/11/2026 los ficheros SEPA solo admiten direcciones estructuradas (al menos"
				" municipio y país). Complete la dirección de: {0}"
			).format(", ".join(problems)),
			title=_("Direcciones incompletas"),
		)
