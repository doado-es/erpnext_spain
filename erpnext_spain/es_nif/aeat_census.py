# Contraste de NIF y nombre con el censo de la AEAT (servicio VNifV2).
#
# Consulta a demanda desde la marca de verificación junto al NIF de clientes y
# proveedores (es_nif/public/js/party.js). No se guarda nada: la respuesta se muestra
# en el formulario y, si el censo tiene otro nombre, se ofrece usarlo.
#
# VNifV2 recibe NIF y nombre y devuelve un Resultado por contribuyente. Solo existe
# en producción (no hay puerto de pruebas), es una consulta sin efecto fiscal y se
# autentica con el certificado de la empresa (ES AEAT Credential), por TLS mutua.
#
# Comportamiento comprobado contra el servicio real (31/10/2026):
# - Persona jurídica: identifica por el NIF (el nombre enviado no influye) y
#   devuelve la razón social del censo («EMPRESA EJEMPLO, SL»).
# - Persona física: IDENTIFICADO aunque el nombre venga en otro orden, y devuelve
#   el nombre en el formato del censo («APELLIDO APELLIDO NOMBRE», con espacios de
#   relleno). VeriFactu, en cambio, rechaza el orden «NOMBRE APELLIDOS» (error
#   103), así que no basta con IDENTIFICADO: se compara el nombre devuelto con el
#   enviado y, si no coincide, el resultado es «Nombre distinto».
# - NIF inexistente: NO IDENTIFICADO.

import re

import frappe
from frappe import _

PARTY_DOCTYPES = ("Customer", "Supplier")
ROLES = ("Accounts User", "Accounts Manager", "Sales Manager", "Purchase Manager", "System Manager")
SERVICE = "VNif"
WSDL_FILE = ("aeat", "vnif", "VNifV2.wsdl")
SERVICE_NAME = "VNifV2Service"
PORT = "VNifPort1"  # www1: certificados de persona y de representante
TIMEOUT = 10.0

IDENTIFIED = "Identificado"
NAME_MISMATCH = "Nombre distinto"
NOT_IDENTIFIED = "No identificado"
UNKNOWN = "Respuesta no reconocida"


# --- comparación de nombres y NIF ------------------------------------------------


def normalize_name(name: str | None) -> str:
	"""Nombre comparable: mayúsculas, sin tildes ni signos y con un espacio entre
	palabras («Empresa Ejemplo, S.L.» → «EMPRESA EJEMPLO SL»)."""
	import unicodedata

	text = unicodedata.normalize("NFKD", name or "")
	text = "".join(char for char in text if not unicodedata.combining(char)).upper()
	text = re.sub(r"[^0-9A-Z ]", " ", text.replace(".", ""))
	return " ".join(text.split())


def clean_nif(tax_id: str | None) -> str:
	value = re.sub(r"[^0-9A-Za-z]", "", tax_id or "").upper()
	return value[2:] if value.startswith("ES") and len(value) > 9 else value


def is_spanish_nif(tax_id: str | None) -> bool:
	from erpnext_spain.es_nif import validator

	value = clean_nif(tax_id)
	return bool(value) and validator.looks_spanish(value)


def status_from(result: str | None, sent_name: str, census_name: str | None) -> str:
	result = (result or "").strip().upper()
	if result == "NO IDENTIFICADO":
		return NOT_IDENTIFIED
	if result != "IDENTIFICADO":
		return UNKNOWN
	if census_name and normalize_name(census_name) != normalize_name(sent_name):
		return NAME_MISMATCH
	return IDENTIFIED


# --- clientes del servicio -------------------------------------------------------


class VNifClient:
	"""Cliente SOAP de VNifV2 con el certificado de la empresa."""

	def __init__(self, company: str):
		from erpnext_spain.es_aeat.client import enabled_credential_pem_paths

		self.cert = enabled_credential_pem_paths(company, SERVICE)

	def check(self, contributors: list[dict]) -> list[dict]:
		import requests
		from zeep import helpers

		from erpnext_spain.es_aeat.client import load_wsdl_client
		from erpnext_spain.schemas import SCHEMA_ROOT

		session = requests.Session()
		session.cert = self.cert
		client = load_wsdl_client(
			str(SCHEMA_ROOT.joinpath(*WSDL_FILE)),
			session=session,
			timeout=TIMEOUT,
			service_name=SERVICE_NAME,
			port_name=PORT,
		)
		response = client.service.VNifV2(Contribuyente=contributors)
		return helpers.serialize_object(response, dict) or []


class SimulatedVNifClient:
	"""Tests: `frappe.flags.es_vnif_responses` = {NIF: (Resultado, Nombre devuelto)};
	sin entrada, NO IDENTIFICADO con eco del nombre."""

	def check(self, contributors: list[dict]) -> list[dict]:
		responses = frappe.flags.es_vnif_responses or {}
		rows = []
		for contributor in contributors:
			result, name = responses.get(contributor["Nif"], ("NO IDENTIFICADO", None))
			rows.append(
				{"Nif": contributor["Nif"], "Nombre": name or contributor["Nombre"], "Resultado": result}
			)
		return rows


def client(company: str):
	if frappe.flags.es_vnif_responses is not None:
		return SimulatedVNifClient()
	return VNifClient(company)


# --- endpoint --------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def check_tax_id(doctype: str, tax_id: str, party_name: str, company: str | None = None) -> dict:
	"""Contrasta NIF y nombre con el censo de la AEAT y devuelve el resultado, sin
	guardar nada. Usa el certificado de `company` o de la compañía por defecto."""
	from erpnext_spain.es_aeat.utils import has_aeat_permission, require_credential

	if doctype not in PARTY_DOCTYPES:
		frappe.throw(_("Solo se contrastan clientes y proveedores."))
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("No tiene permiso para contrastar NIF con la AEAT."), frappe.PermissionError)
	frappe.has_permission(doctype, "read", throw=True)
	if not is_spanish_nif(tax_id):
		frappe.throw(_("La AEAT solo contrasta NIF españoles."))
	company = company or frappe.defaults.get_user_default("Company")
	require_credential(company, _("contrastar NIF con la AEAT"))
	if not has_aeat_permission(frappe.session.user, company):
		frappe.throw(
			_("No tiene permiso para usar el certificado AEAT de {0}.").format(frappe.bold(company)),
			frappe.PermissionError,
		)

	sent_name = (party_name or "").strip()[:120]
	rows = client(company).check([{"Nif": clean_nif(tax_id), "Nombre": sent_name}])
	row = rows[0] if rows else {}
	census_name = " ".join((row.get("Nombre") or "").split()) or None
	status = status_from(row.get("Resultado"), sent_name, census_name)
	return {
		"status": status,
		"result": row.get("Resultado"),
		"census_name": census_name if status == NAME_MISMATCH else None,
	}
