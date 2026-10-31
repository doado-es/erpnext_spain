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


class ViesClient:
	def check(self, country: str, number: str) -> dict:
		import requests

		response = requests.post(VIES_URL, json={"countryCode": country, "vatNumber": number}, timeout=15)
		response.raise_for_status()
		data = response.json()
		return {"valid": bool(data.get("valid")), "name": (data.get("name") or "").strip()}


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
	from erpnext_spain.nif import validator

	doc = frappe.get_doc(doctype, name)
	values = {"es_vies_checked_on": now_datetime(), "es_vies_name": None}
	parts = split_vat(doc.tax_id)
	if parts:
		try:
			result = client().check(*parts)
			values["es_vies_status"] = VALID if result["valid"] else INVALID
			values["es_vies_name"] = (result.get("name") or "")[:140] or None
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
		frappe.enqueue("erpnext_spain.nif.vies.run", queue="long", doctype=doctype, names=names)
		return {"queued": True, "count": len(names)}
	return run(doctype, names)


def run(doctype: str, names: list[str]) -> dict:
	result = {}
	for name in names:
		result[name] = check_party(doctype, name)
	return result
