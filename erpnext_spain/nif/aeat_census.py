# Contraste de NIF y nombre con el censo de la AEAT (servicio VNifV2).
#
# Servicio de la AEAT de identificación de NIF: recibe NIF y nombre (hasta 20.000
# por petición) y devuelve un Resultado por contribuyente. Solo existe en
# producción (no hay puerto de pruebas) y es una consulta sin efecto fiscal; se
# autentica con el certificado de la empresa (ES AEAT Credential), por TLS mutua.
#
# Comportamiento comprobado contra el servicio real (31/10/2026):
# - Persona jurídica: identifica por el NIF (el nombre enviado no influye) y
#   devuelve la razón social del censo («EMPRESA EJEMPLO, SL»).
# - Persona física: IDENTIFICADO aunque el nombre venga en otro orden, y devuelve
#   el nombre en el formato del censo («APELLIDO APELLIDO NOMBRE», con espacios de
#   relleno). VeriFactu, en cambio, rechaza el orden «NOMBRE APELLIDOS» (error
#   103), así que no basta con IDENTIFICADO: se compara el nombre devuelto con el
#   del tercero y, si no coincide, se marca «Nombre distinto» y se ofrece el del
#   censo.
# - NIF inexistente: NO IDENTIFICADO.
#
# Cuándo se contrasta:
# - Al guardar el tercero (doc_event on_change) si cambian el NIF o el nombre, con
#   el certificado de la compañía por defecto del usuario. Un fallo de la AEAT no
#   bloquea el guardado: queda sin contrastar y se anota en el Error Log.
# - Con el botón «Contrastar con la AEAT» y la acción masiva de la lista.
# - Una factura aceptada (Correcto) por VeriFactu o el SII con el mismo NIF y
#   nombre que el tercero lo marca como identificado sin llamada extra.

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

PARTY_DOCTYPES = ("Customer", "Supplier")
NAME_FIELDS = {"Customer": "customer_name", "Supplier": "supplier_name"}
ROLES = ("Accounts User", "Accounts Manager", "Sales Manager", "Purchase Manager", "System Manager")
SERVICE = "VNif"
WSDL_FILE = ("aeat", "vnif", "VNifV2.wsdl")
SERVICE_NAME = "VNifV2Service"
PORT = "VNifPort1"  # www1: certificados de persona y de representante
BATCH = 500
QUEUE_ABOVE = 20
TIMEOUT = 15.0
ON_SAVE_TIMEOUT = 5.0  # al guardar el formulario: no hacer esperar al usuario

IDENTIFIED = "Identificado"
NAME_MISMATCH = "Nombre distinto"
NOT_IDENTIFIED = "No identificado"
UNKNOWN = "Respuesta no reconocida"
STATUSES = (IDENTIFIED, NAME_MISMATCH, NOT_IDENTIFIED, UNKNOWN)

SOURCE_SERVICE = "Consulta de NIF"
SOURCE_VERIFACTU = "VeriFactu"
SOURCE_SII = "SII"
SOURCES = (SOURCE_SERVICE, SOURCE_VERIFACTU, SOURCE_SII)

STATUS = "es_aeat_status"
RESULT = "es_aeat_result"
CENSUS_NAME = "es_aeat_census_name"
CHECKED_ON = "es_aeat_checked_on"
SOURCE = "es_aeat_source"
STATE_FIELDS = (STATUS, RESULT, CENSUS_NAME, CHECKED_ON, SOURCE)


def party_fields(insert_after: str) -> list[dict]:
	read_only = {"read_only": 1, "no_copy": 1, "depends_on": f"eval:doc.{CHECKED_ON}"}
	return [
		{
			"fieldname": STATUS,
			"label": "Contraste con la AEAT",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(STATUSES),
			"insert_after": insert_after,
			"in_list_view": 1,
			"in_standard_filter": 1,
			**read_only,
		},
		{
			"fieldname": CENSUS_NAME,
			"label": "Nombre en el censo de la AEAT",
			"fieldtype": "Data",
			"insert_after": STATUS,
			**read_only,
		},
		{
			"fieldname": RESULT,
			"label": "Respuesta de la AEAT",
			"fieldtype": "Data",
			"insert_after": CENSUS_NAME,
			**read_only,
		},
		{
			"fieldname": SOURCE,
			"label": "Origen del contraste",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(SOURCES),
			"insert_after": RESULT,
			**read_only,
		},
		{
			"fieldname": CHECKED_ON,
			"label": "Fecha del contraste",
			"fieldtype": "Datetime",
			"insert_after": SOURCE,
			"read_only": 1,
			"no_copy": 1,
			"hidden": 1,
		},
	]


# --- comparación de nombres ----------------------------------------------------


def normalize_name(name: str | None) -> str:
	"""Nombre comparable: mayúsculas, sin tildes ni signos y con un espacio entre
	palabras («Empresa Ejemplo, S.L.» → «EMPRESA EJEMPLO SL»)."""
	import unicodedata

	text = unicodedata.normalize("NFKD", name or "")
	text = "".join(char for char in text if not unicodedata.combining(char)).upper()
	text = re.sub(r"[^0-9A-ZÑ ]", " ", text.replace(".", ""))
	return " ".join(text.split())


def clean_nif(tax_id: str | None) -> str:
	value = re.sub(r"[^0-9A-Za-z]", "", tax_id or "").upper()
	return value[2:] if value.startswith("ES") and len(value) > 9 else value


def is_spanish_nif(tax_id: str | None) -> bool:
	from erpnext_spain.nif import validator

	value = clean_nif(tax_id)
	return bool(value) and validator.looks_spanish(value)


# --- clientes del servicio -----------------------------------------------------


class VNifClient:
	"""Cliente SOAP de VNifV2 con el certificado de la empresa."""

	def __init__(self, company: str, timeout: float = TIMEOUT):
		from erpnext_spain.aeat.client import enabled_credential_pem_paths

		self.cert = enabled_credential_pem_paths(company, SERVICE)
		self.timeout = timeout

	def check(self, contributors: list[dict]) -> list[dict]:
		import requests
		from zeep import helpers

		from erpnext_spain.aeat.client import load_wsdl_client
		from erpnext_spain.schemas import SCHEMA_ROOT

		session = requests.Session()
		session.cert = self.cert
		client = load_wsdl_client(
			str(SCHEMA_ROOT.joinpath(*WSDL_FILE)),
			session=session,
			timeout=self.timeout,
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


def client(company: str, timeout: float = TIMEOUT):
	if frappe.flags.es_vnif_responses is not None:
		return SimulatedVNifClient()
	return VNifClient(company, timeout)


# --- estado del tercero --------------------------------------------------------


def status_from(result: str, sent_name: str, census_name: str | None) -> str:
	result = (result or "").strip().upper()
	if result == "NO IDENTIFICADO":
		return NOT_IDENTIFIED
	if result != "IDENTIFICADO":
		return UNKNOWN
	if census_name and normalize_name(census_name) != normalize_name(sent_name):
		return NAME_MISMATCH
	return IDENTIFIED


def save_state(doctype: str, name: str, values: dict) -> None:
	frappe.db.set_value(doctype, name, values, update_modified=False)


def check_parties_now(doctype: str, names: list[str], company: str) -> dict:
	"""Consulta VNifV2 por lotes y guarda el resultado de cada tercero."""
	name_field = NAME_FIELDS[doctype]
	parties = frappe.get_all(
		doctype, filters={"name": ("in", names)}, fields=["name", "tax_id", f"{name_field} as party_name"]
	)
	summary = {}
	pending = []
	for party in parties:
		if not is_spanish_nif(party.tax_id):
			summary[party.name] = _("Sin NIF español")
			continue
		pending.append(party)

	service = client(company) if pending else None
	for start in range(0, len(pending), BATCH):
		batch = pending[start : start + BATCH]
		contributors = [contributor_of(p.tax_id, p.party_name) for p in batch]
		rows = service.check(contributors)
		for party, contributor, row in zip(batch, contributors, rows, strict=False):
			values = state_from_row(row, contributor["Nombre"])
			save_state(doctype, party.name, values)
			summary[party.name] = values[STATUS]
	return summary


def contributor_of(tax_id: str | None, name: str | None) -> dict:
	return {"Nif": clean_nif(tax_id), "Nombre": (name or "")[:120]}


def state_from_row(row: dict, sent_name: str) -> dict:
	"""Valores del tercero a partir de la respuesta de VNifV2 para un contribuyente."""
	census_name = " ".join((row.get("Nombre") or "").split()) or None
	status = status_from(row.get("Resultado"), sent_name, census_name)
	return {
		STATUS: status,
		RESULT: (row.get("Resultado") or "")[:140],
		CENSUS_NAME: census_name if status == NAME_MISMATCH else None,
		SOURCE: SOURCE_SERVICE,
		CHECKED_ON: now_datetime(),
	}


@frappe.whitelist(methods=["POST"])
def check_parties(doctype: str, names: list | str, company: str | None = None) -> dict:
	"""Contraste con la AEAT de clientes o proveedores (en segundo plano si son
	más de 20). Usa el certificado de `company` o de la compañía por defecto."""
	from erpnext_spain.aeat.utils import has_aeat_permission, require_credential
	from erpnext_spain.es_facturacion.bulk import as_list

	if doctype not in PARTY_DOCTYPES:
		frappe.throw(_("Solo se contrastan clientes y proveedores."))
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("No tiene permiso para contrastar NIF con la AEAT."), frappe.PermissionError)
	frappe.has_permission(doctype, "write", throw=True)
	company = company or frappe.defaults.get_user_default("Company")
	require_credential(company, _("contrastar NIF con la AEAT"))
	if not has_aeat_permission(frappe.session.user, company):
		frappe.throw(
			_("No tiene permiso para usar el certificado AEAT de {0}.").format(frappe.bold(company)),
			frappe.PermissionError,
		)
	names = as_list(names)
	if len(names) > QUEUE_ABOVE:
		frappe.enqueue(
			"erpnext_spain.nif.aeat_census.check_parties_now",
			queue="long",
			doctype=doctype,
			names=names,
			company=company,
		)
		return {"queued": True, "count": len(names)}
	return check_parties_now(doctype, names, company)


def reset_if_changed(doc: Document, method: str | None = None) -> None:
	"""doc_event validate de Customer y Supplier: si cambian el NIF o el nombre, el
	contraste anterior ya no vale. Si el nombre nuevo es el del censo (botón «Usar
	el nombre del censo»), queda identificado."""
	if doc.is_new() or not doc.get(STATUS):
		return
	name_field = NAME_FIELDS[doc.doctype]
	if not (doc.has_value_changed("tax_id") or doc.has_value_changed(name_field)):
		return
	census_name = doc.get(CENSUS_NAME)
	if (
		not doc.has_value_changed("tax_id")
		and census_name
		and normalize_name(doc.get(name_field)) == normalize_name(census_name)
	):
		doc.set(STATUS, IDENTIFIED)
		doc.set(CENSUS_NAME, None)
		return
	for fieldname in STATE_FIELDS:
		doc.set(fieldname, None)


def census_company() -> str | None:
	"""Compañía cuyo certificado contrasta al guardar: la compañía por defecto del
	usuario, si tiene certificado AEAT habilitado y el usuario puede usarlo."""
	from erpnext_spain.aeat.utils import company_credential, has_aeat_permission

	company = frappe.defaults.get_user_default("Company")
	if not company or not company_credential(company):
		return None
	return company if has_aeat_permission(frappe.session.user, company) else None


def on_change(doc: Document, method: str | None = None) -> None:
	"""doc_event on_change de Customer y Supplier: contraste al guardar si cambian el
	NIF o el nombre. El resultado se guarda y se copia al documento para que el
	formulario lo muestre sin recargar. Nunca bloquea el guardado."""
	name_field = NAME_FIELDS.get(doc.doctype)
	if not name_field or not (doc.has_value_changed("tax_id") or doc.has_value_changed(name_field)):
		return
	if doc.get(STATUS) or not is_spanish_nif(doc.get("tax_id")):
		return  # ya identificado al aplicar el nombre del censo, o NIF no español
	flags = frappe.flags
	if flags.in_import or flags.in_patch or flags.in_install or flags.in_migrate:
		return
	if flags.in_test and flags.es_vnif_responses is None:
		return  # los tests nunca llaman a la AEAT real
	company = census_company()
	if not company:
		return
	try:
		contributor = contributor_of(doc.tax_id, doc.get(name_field))
		rows = client(company, ON_SAVE_TIMEOUT).check([contributor])
		if not rows:
			return
		values = state_from_row(rows[0], contributor["Nombre"])
	except Exception:
		frappe.log_error(
			title=f"Contraste con la AEAT al guardar {doc.doctype} {doc.name}", message=frappe.get_traceback()
		)
		return
	save_state(doc.doctype, doc.name, values)
	doc.update(values)


def mark_from_submission(
	doctype: str, party: str | None, nif: str | None, name: str | None, source: str
) -> None:
	"""La AEAT aceptó (Correcto) un registro con este NIF y nombre: si siguen siendo
	los del tercero, queda identificado. Nunca lanza: corre dentro del procesado
	de respuestas de VeriFactu y el SII."""
	try:
		if not party or not nif or not frappe.db.exists(doctype, party):
			return
		values = frappe.db.get_value(doctype, party, ["tax_id", NAME_FIELDS[doctype]], as_dict=True)
		if clean_nif(values.tax_id) != clean_nif(nif):
			return
		if normalize_name(values.get(NAME_FIELDS[doctype])) != normalize_name(name):
			return
		save_state(
			doctype,
			party,
			{
				STATUS: IDENTIFIED,
				RESULT: _("Registro aceptado por la AEAT"),
				CENSUS_NAME: None,
				SOURCE: source,
				CHECKED_ON: now_datetime(),
			},
		)
	except Exception:
		frappe.log_error(title=f"Contraste de NIF desde {source}", message=frappe.get_traceback())
