# Comprobación de NIF-IVA europeos en VIES (spec 15, F4).
#
# API REST de la Comisión Europea (check-vat-number). Adaptador con cliente real
# y simulado (tests). El contraste con el censo de la AEAT (requiere
# certificado) queda pendiente.

import re

import frappe
from frappe import _
from frappe.utils import now_datetime

VIES_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"
VALID, INVALID, UNAVAILABLE, NOT_EU, SPANISH_OK, SPANISH_WRONG = (
	"Válido",
	"No válido",
	"No disponible",
	"No es de la UE",
	"NIF español válido",
	"NIF español no válido",
)
ROLES = ("Accounts User", "Accounts Manager", "Sales Manager", "Purchase Manager", "System Manager")
PARTY_DOCTYPES = ("Customer", "Supplier")


# VIES devuelve «---» cuando el Estado miembro no facilita el dato.
NOT_PROVIDED = "---"


def provided(value: str | None) -> str:
	value = (value or "").strip()
	return "" if value == NOT_PROVIDED else value


def requester() -> dict:
	"""NIF-IVA de la compañía por defecto del usuario: con él VIES devuelve un número
	de consulta que sirve de justificante."""
	from erpnext_spain.es_nif import validator

	company = frappe.defaults.get_user_default("Company")
	tax_id = (frappe.get_cached_value("Company", company, "tax_id") or "") if company else ""
	number = re.sub(r"[^0-9A-Za-z]", "", tax_id).upper().removeprefix("ES")
	if not number or not validator.looks_spanish(number):
		return {}
	return {"requesterMemberStateCode": "ES", "requesterNumber": number}


class ViesClient:
	def check(self, country: str, number: str) -> dict:
		import requests

		payload = {"countryCode": country, "vatNumber": number, **requester()}
		response = requests.post(VIES_URL, json=payload, timeout=15)
		response.raise_for_status()
		data = response.json()
		return {
			"valid": bool(data.get("valid")),
			"name": provided(data.get("name")),
			"address": provided(data.get("address")),
			"request_identifier": provided(data.get("requestIdentifier")),
		}


class SimulatedViesClient:
	"""Respuestas fijadas en `frappe.flags.es_vies_responses` por NIF-IVA; un valor
	`None` simula el servicio caído."""

	def check(self, country: str, number: str) -> dict:
		responses = frappe.flags.es_vies_responses or {}
		value = responses.get(f"{country}{number}")
		if value is None:
			raise ConnectionError("VIES no disponible")
		return value


def client():
	return SimulatedViesClient() if frappe.flags.es_vies_responses is not None else ViesClient()


def split_vat(tax_id: str | None) -> tuple[str, str] | None:
	from erpnext_spain.es_efactura.codes import EU_COUNTRIES

	value = re.sub(r"[^0-9A-Za-z]", "", tax_id or "").upper()
	if len(value) > 4 and value[:2] in EU_COUNTRIES and value[:2] != "ES":
		return value[:2], value[2:]
	return None


def check_party(doctype: str, name: str) -> str:
	"""Comprueba el NIF de un cliente o proveedor y guarda el resultado."""
	from erpnext_spain.es_nif import validator

	doc = frappe.get_doc(doctype, name)
	values = {
		"es_vies_checked_on": now_datetime(),
		"es_vies_name": None,
		"es_vies_address": None,
		"es_vies_request_id": None,
	}
	parts = split_vat(doc.tax_id)
	if parts:
		try:
			result = client().check(*parts)
			values["es_vies_status"] = VALID if result["valid"] else INVALID
			values["es_vies_name"] = provided(result.get("name"))[:140] or None
			values["es_vies_address"] = provided(result.get("address")) or None
			values["es_vies_request_id"] = provided(result.get("request_identifier"))[:140] or None
		except Exception:
			values["es_vies_status"] = UNAVAILABLE
	elif doc.tax_id and validator.looks_spanish(doc.tax_id):
		try:
			validator.validate_spanish_tax_id(doc.tax_id)
			values["es_vies_status"] = SPANISH_OK
		except validator.InvalidTaxID:
			values["es_vies_status"] = SPANISH_WRONG
	else:
		values["es_vies_status"] = NOT_EU
	frappe.db.set_value(doctype, name, values, update_modified=False)
	return values["es_vies_status"]


@frappe.whitelist(methods=["POST"])
def check_parties(doctype: str, names: list | str) -> dict:
	"""Comprobación masiva (en segundo plano si son más de 20)."""
	from erpnext_spain.es_facturacion.bulk import as_list

	if doctype not in PARTY_DOCTYPES:
		frappe.throw(_("Solo se comprueban clientes y proveedores."))
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("No tiene permiso para comprobar NIF."), frappe.PermissionError)
	frappe.has_permission(doctype, "write", throw=True)
	names = as_list(names)
	if len(names) > 20:
		frappe.enqueue("erpnext_spain.es_nif.vies.run", queue="long", doctype=doctype, names=names)
		return {"queued": True, "count": len(names)}
	return run(doctype, names)


def run(doctype: str, names: list[str]) -> dict:
	result = {}
	for name in names:
		result[name] = check_party(doctype, name)
	return result


# --- completar el tercero con los datos de VIES -----------------------------------------


def parse_address(address: str | None, country_code: str) -> dict | None:
	"""Dirección de ERPNext a partir del texto libre de VIES (una línea por dato).

	La última línea suele ser «código postal + población» (10115 BERLIN, 75001 PARIS);
	si no, va entera como población."""
	lines = [line.strip() for line in (address or "").splitlines() if line.strip()]
	if not lines:
		return None
	last = lines[-1] if len(lines) > 1 else ""
	# Primero el formato neerlandés («1012 AB AMSTERDAM»); luego el general.
	match = re.match(r"^(\d{4}\s?[A-Z]{2})\s+(.+)$", last) or re.match(
		r"^(?:[A-Z]{1,2}-)?(\S*\d\S*)\s+(.+)$", last
	)
	pincode, city = (match.group(1), match.group(2)) if match else ("", last)
	street = lines[:-1] if len(lines) > 1 else lines
	code = "gr" if country_code == "EL" else country_code.lower()
	return {
		"address_line1": street[0][:140],
		"address_line2": ", ".join(street[1:])[:140] or None,
		"pincode": pincode or None,
		"city": (city or street[-1])[:140],
		"country": frappe.db.get_value("Country", {"code": code}, "name"),
	}


def check_permissions(doctype: str, name: str) -> None:
	if doctype not in PARTY_DOCTYPES:
		frappe.throw(_("Solo se comprueban clientes y proveedores."))
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("No tiene permiso para comprobar NIF."), frappe.PermissionError)
	frappe.get_doc(doctype, name).check_permission("write")


@frappe.whitelist(methods=["POST"])
def vies_details(doctype: str, name: str) -> dict:
	"""Comprueba el NIF-IVA en VIES y devuelve lo registrado (nombre, dirección y la
	dirección que se crearía)."""
	check_permissions(doctype, name)
	status = check_party(doctype, name)
	values = frappe.db.get_value(
		doctype, name, ["tax_id", "es_vies_name", "es_vies_address", "es_vies_request_id"], as_dict=True
	)
	parts = split_vat(values.tax_id)
	return {
		"status": status,
		"name": values.es_vies_name,
		"address": values.es_vies_address,
		"request_identifier": values.es_vies_request_id,
		"parsed_address": parse_address(values.es_vies_address, parts[0]) if parts else None,
	}


@frappe.whitelist(methods=["POST"])
def apply_vies_details(
	doctype: str, name: str, update_name: bool = False, create_address: bool = False
) -> dict:
	"""Usa los datos guardados de la última consulta válida a VIES: nombre del tercero
	y dirección de facturación. No se fía de datos enviados por el navegador."""
	from frappe.utils import cint

	check_permissions(doctype, name)
	values = frappe.db.get_value(
		doctype, name, ["tax_id", "es_vies_status", "es_vies_name", "es_vies_address"], as_dict=True
	)
	if values.es_vies_status != VALID:
		frappe.throw(_("Compruebe antes el NIF-IVA en VIES: el último resultado no es válido."))
	result = {"name": None, "address": None}
	if cint(update_name) and values.es_vies_name:
		field = "customer_name" if doctype == "Customer" else "supplier_name"
		frappe.db.set_value(doctype, name, field, values.es_vies_name)
		result["name"] = values.es_vies_name
	parts = split_vat(values.tax_id)
	parsed = parse_address(values.es_vies_address, parts[0]) if parts else None
	if cint(create_address) and parsed:
		result["address"] = billing_address(doctype, name, parsed)
	return result


def billing_address(doctype: str, name: str, parsed: dict) -> str:
	"""Dirección de facturación del tercero con los datos de VIES (no la duplica)."""
	existing = frappe.get_all(
		"Address",
		filters=[
			["Dynamic Link", "link_doctype", "=", doctype],
			["Dynamic Link", "link_name", "=", name],
			["Address", "address_line1", "=", parsed["address_line1"]],
		],
		pluck="name",
	)
	if existing:
		return existing[0]
	has_primary = frappe.get_all(
		"Address",
		filters=[
			["Dynamic Link", "link_doctype", "=", doctype],
			["Dynamic Link", "link_name", "=", name],
			["Address", "is_primary_address", "=", 1],
		],
		limit=1,
	)
	address = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": name,
			"address_type": "Billing",
			**{k: v for k, v in parsed.items() if v},
			"is_primary_address": 0 if has_primary else 1,
			"links": [{"link_doctype": doctype, "link_name": name}],
		}
	)
	address.insert()
	return address.name
