# SII: generación de registros, plazos, envío por el outbox de la capa AEAT,
# reenvío y cuadre (spec 14 §3-§4).

import json
import os
from typing import ClassVar

import frappe
from frappe import _
from frappe.utils import add_days, add_months, get_first_day, getdate, now_datetime

from erpnext_spain.aeat.manager import AEATDriver
from erpnext_spain.es_sii import records
from erpnext_spain.utils.gating import is_sii_active

SERVICE = "SII"
PENDING, SENT, OK, OK_WITH_ERRORS, WRONG, VOIDED, REPLACED = (
	"Pendiente",
	"Enviado",
	"Correcto",
	"Aceptado con errores",
	"Incorrecto",
	"Anulado",
	"Sustituido",
)
ACCEPTED = (OK, OK_WITH_ERRORS)
BOOKS = {"Sales Invoice": records.ISSUED, "Purchase Invoice": records.RECEIVED}
HOLIDAY_LIST = "Festivos nacionales España"
WORKING_DAYS = 4
ALLOWED_ROLES = ("Accounts Manager", "System Manager")


# --- plazos ----------------------------------------------------------------------------


def holidays() -> set:
	if not frappe.db.exists("Holiday List", HOLIDAY_LIST):
		return set()
	return {
		getdate(d) for d in frappe.get_all("Holiday", filters={"parent": HOLIDAY_LIST}, pluck="holiday_date")
	}


def add_working_days(start, days: int):
	"""Suma días hábiles: sin sábados, domingos ni festivos nacionales."""
	current, closed, left = getdate(start), holidays(), days
	while left:
		current = add_days(current, 1)
		if current.weekday() < 5 and current not in closed:
			left -= 1
	return getdate(current)


def deadline(book: str, date) -> object:
	limit = add_working_days(date, WORKING_DAYS)
	if book == records.RECEIVED:
		# En todo caso, antes del día 16 del mes siguiente al periodo **[revisar]**.
		limit = min(limit, getdate(add_days(get_first_day(add_months(date, 1)), 14)))
	return limit


# --- generación ------------------------------------------------------------------------


def new_record(doc, communication: str, content: dict, previous=None) -> str:
	book = BOOKS[doc.doctype]
	identification = content["IDFactura"]
	issuer = identification["IDEmisorFactura"]
	record = frappe.get_doc(
		{
			"doctype": "ES Sii Record",
			"company": doc.company,
			"book": book,
			"voucher_type": doc.doctype,
			"voucher_no": doc.name,
			"communication": communication,
			"status": PENDING,
			"deadline": deadline(
				book, doc.posting_date if communication != records.CANCEL else now_datetime()
			),
			"issuer_nif": issuer.get("NIF") or (issuer.get("IDOtro") or {}).get("ID"),
			"invoice_number": identification["NumSerieFacturaEmisor"],
			"issue_date": identification["FechaExpedicionFacturaEmisor"],
			"content": json.dumps(content, ensure_ascii=False, indent=1),
		}
	)
	record.flags.ignore_permissions = True
	record.insert()
	if previous:
		frappe.db.set_value("ES Sii Record", previous, "status", REPLACED, update_modified=False)
	return record.name


def on_submit(doc, method=None) -> None:
	if not is_sii_active(doc.company):
		return
	new_record(doc, records.NEW, records.build_record(doc))


def on_cancel(doc, method=None) -> None:
	if not is_sii_active(doc.company):
		return
	last = latest_record(doc)
	if not last:
		return
	if last.status == PENDING:
		frappe.db.set_value("ES Sii Record", last.name, "status", VOIDED, update_modified=False)
		return
	if last.status in ACCEPTED or last.status == SENT:
		content = records.cancellation_record(last.book, json.loads(last.content))
		new_record(doc, records.CANCEL, content)


def latest_record(doc):
	rows = frappe.get_all(
		"ES Sii Record",
		filters={"voucher_type": doc.doctype, "voucher_no": doc.name, "status": ["!=", REPLACED]},
		fields=["name", "status", "book", "content", "communication"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


@frappe.whitelist(methods=["POST"])
def resend(record: str) -> str:
	"""Reenvía una factura rechazada o corregida con los datos actuales: alta (A0)
	si la AEAT nunca la aceptó, modificación (A1) si ya estaba registrada."""
	check_role()
	old = frappe.get_doc("ES Sii Record", record)
	frappe.get_doc(old.voucher_type, old.voucher_no).check_permission("write")
	accepted_before = frappe.db.exists(
		"ES Sii Record",
		{"voucher_type": old.voucher_type, "voucher_no": old.voucher_no, "status": ["in", ACCEPTED]},
	)
	doc = frappe.get_doc(old.voucher_type, old.voucher_no)
	return new_record(
		doc, records.CHANGE if accepted_before else records.NEW, records.build_record(doc), previous=old.name
	)


def check_role() -> None:
	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Solo un usuario con rol Accounts Manager puede enviar al SII."), frappe.PermissionError
		)


# --- driver del outbox ---------------------------------------------------------------------


class SiiClient:
	"""Cliente SOAP del SII: un WSDL por libro (expedidas y recibidas)."""

	PORTS: ClassVar[dict[tuple[str, str], str]] = {
		(records.ISSUED, "pruebas"): "SuministroFactEmitidasPruebas",
		(records.ISSUED, "produccion"): "SuministroFactEmitidas",
		(records.RECEIVED, "pruebas"): "SuministroFactRecibidasPruebas",
		(records.RECEIVED, "produccion"): "SuministroFactRecibidas",
	}

	def __init__(self, company: str, environment: str):
		from erpnext_spain.aeat.client import enabled_credential_pem_paths

		self.company = company
		self.environment = environment
		self.cert_pem, self.key_pem = enabled_credential_pem_paths(company, SERVICE)
		self.clients = {}

	def send(self, payload: dict) -> dict:
		import requests
		from zeep import helpers

		from erpnext_spain.aeat.client import load_wsdl_client

		book = payload["book"]
		if book not in self.clients:
			session = requests.Session()
			session.cert = (self.cert_pem, self.key_pem)
			path = os.path.join(
				frappe.get_app_path("erpnext_spain", "schemas", "aeat", "sii"), records.WSDL[book]
			)
			self.clients[book] = load_wsdl_client(
				path,
				session=session,
				service_name="siiService",
				port_name=self.PORTS[(book, self.environment)],
			)
		response = getattr(self.clients[book].service, payload["operacion"])(**payload["datos"])
		return dict(helpers.serialize_object(response, dict))


class SiiDriver(AEATDriver):
	service = SERVICE

	def __init__(self, client: object | None = None):
		self.client = client

	def get_companies(self) -> list[str]:
		return frappe.get_all("ES Sii Record", filters={"status": PENDING}, pluck="company", distinct=True)

	def get_pending(self, company: str) -> list:
		first = frappe.get_all(
			"ES Sii Record",
			filters={"company": company, "status": PENDING},
			fields=["book", "communication"],
			order_by="creation",
			limit=1,
		)
		if not first:
			return []
		book, communication = first[0].book, first[0].communication
		# Altas y modificaciones van juntas (misma operación); las bajas, aparte.
		communications = (
			[records.CANCEL] if communication == records.CANCEL else [records.NEW, records.CHANGE]
		)
		return frappe.get_all(
			"ES Sii Record",
			filters={
				"company": company,
				"status": PENDING,
				"book": book,
				"communication": ["in", communications],
			},
			fields=["name", "book", "communication", "content", "invoice_number", "issuer_nif"],
			order_by="creation",
			limit=self.batch_limit(company),
		)

	def build_payload(self, company: str, pending: list) -> dict:
		book = pending[0].book
		communication = pending[0].communication
		# Una petición SII lleva un único TipoComunicacion: si hay modificaciones se envían todas como A1.
		if communication != records.CANCEL and any(r.communication == records.CHANGE for r in pending):
			communication = records.CHANGE
		data = records.payload(company, book, communication, [json.loads(r.content) for r in pending])
		data["book"] = book
		data["records"] = [r.name for r in pending]
		for record in pending:
			frappe.db.set_value(
				"ES Sii Record",
				record.name,
				{
					"attempts": (frappe.db.get_value("ES Sii Record", record.name, "attempts") or 0) + 1,
					"last_attempt": now_datetime(),
				},
				update_modified=False,
			)
		return data

	def get_client(self, company: str):
		if self.client is not None:
			return self.client
		environment = (
			"pruebas"
			if frappe.get_cached_value("Company", company, "es_sii_test_mode") == "Pruebas"
			else "produccion"
		)
		return SiiClient(company, environment)

	def send(self, client, payload: dict) -> dict:
		data = {k: v for k, v in payload.items() if k not in ("book", "records")}
		response = client.send({**data, "book": payload["book"]})
		response["_records"] = payload["records"]
		return response

	def process_response(self, response: dict, response_doc) -> None:
		lines = response.get("RespuestaLinea") or []
		by_number = {}
		for line in lines:
			number = ((line.get("IDFactura") or {}).get("NumSerieFacturaEmisor") or "").strip()
			by_number[number] = line
		for name in response.get("_records") or []:
			record = frappe.get_doc("ES Sii Record", name)
			line = by_number.get(record.invoice_number)
			if not line:
				status, code, description = (
					WRONG,
					None,
					_("La AEAT no devolvió respuesta para este registro."),
				)
			else:
				state = line.get("EstadoRegistro")
				status = {"Correcto": OK, "AceptadoConErrores": OK_WITH_ERRORS}.get(state, WRONG)
				code = line.get("CodigoErrorRegistro")
				description = line.get("DescripcionErrorRegistro")
			values = {
				"status": status,
				"error_code": code,
				"error_description": description,
				"csv": response.get("CSV"),
				"aeat_response": getattr(response_doc, "name", None),
			}
			frappe.db.set_value("ES Sii Record", name, values, update_modified=False)

	def rate_limit_seconds(self, company: str) -> int:
		return 0

	def on_batch_failure(self, company: str, pending: list, error: Exception) -> None:
		for record in pending:
			frappe.db.set_value(
				"ES Sii Record", record.name, {"error_description": f"{error!r}"[:500]}, update_modified=False
			)


def drain_outbox() -> None:
	"""Job programado: envía los registros pendientes de todas las compañías."""
	from erpnext_spain.aeat.manager import AEATOutboxManager

	AEATOutboxManager().drain([SiiDriver()])


# --- avisos de plazo y cuadre ----------------------------------------------------------------


def warn_deadlines() -> None:
	"""Job diario: registros pendientes o incorrectos que vencen hoy, mañana o ya vencidos."""
	from frappe.utils import nowdate

	limit = add_days(nowdate(), 1)
	for company in frappe.get_all(
		"ES Sii Record",
		filters={"status": ["in", [PENDING, WRONG]], "deadline": ["<=", limit]},
		pluck="company",
		distinct=True,
	):
		count = frappe.db.count(
			"ES Sii Record",
			{"company": company, "status": ["in", [PENDING, WRONG]], "deadline": ["<=", limit]},
		)
		for user in frappe.get_all(
			"Has Role", filters={"role": "Accounts Manager", "parenttype": "User"}, pluck="parent"
		):
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": user,
					"type": "Alert",
					"document_type": "Company",
					"document_name": company,
					"subject": _("SII de {0}: {1} registros vencen hoy, mañana o ya han vencido.").format(
						company, count
					),
				}
			).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def reconcile_with_aeat(company: str, book: str, year: int, month: int) -> dict:
	"""Compara lo registrado en la AEAT con el Registro Fiscal IVA del periodo."""
	check_role()
	frappe.get_doc("Company", company).check_permission("read")
	return compare(company, book, int(year), int(month), query_aeat(company, book, int(year), int(month)))


def query_aeat(company: str, book: str, year: int, month: int, client=None) -> list[dict]:
	"""Facturas registradas en la AEAT del periodo: [{"number", "base", "quota"}]."""
	driver = SiiDriver(client)
	operation = "ConsultaLRFacturasEmitidas" if book == records.ISSUED else "ConsultaLRFacturasRecibidas"
	response = driver.get_client(company).send(
		{
			"book": book,
			"operacion": operation,
			"datos": {
				"Cabecera": records.header(company, None),
				"FiltroConsulta": {"PeriodoLiquidacion": {"Ejercicio": str(year), "Periodo": f"{month:02d}"}},
			},
		}
	)
	result = []
	for row in (
		response.get(
			"RegistroRespuestaConsultaLRFacturasEmitidas"
			if book == records.ISSUED
			else "RegistroRespuestaConsultaLRFacturasRecibidas"
		)
		or []
	):
		invoice = row.get("DatosFacturaEmitida") or row.get("DatosFacturaRecibida") or {}
		result.append(
			{
				"number": (row.get("IDFactura") or {}).get("NumSerieFacturaEmisor"),
				"total": float(invoice.get("ImporteTotal") or 0),
			}
		)
	return result


def compare(company: str, book: str, year: int, month: int, registered: list[dict]) -> dict:
	from frappe.utils import get_last_day

	doctype = "Sales Invoice" if book == records.ISSUED else "Purchase Invoice"
	start = getdate(f"{year}-{month:02d}-01")
	fields = ["name", "base_grand_total"] + (["bill_no"] if book == records.RECEIVED else [])
	invoices = frappe.get_all(
		doctype,
		filters={
			"company": company,
			"docstatus": 1,
			"posting_date": ["between", [start, get_last_day(start)]],
		},
		fields=fields,
	)
	ours = {(r.get("bill_no") or r.name): float(r.base_grand_total or 0) for r in invoices}
	theirs = {r["number"]: r["total"] for r in registered}
	return {
		"missing_in_aeat": sorted(set(ours) - set(theirs)),
		"not_in_books": sorted(set(theirs) - set(ours)),
		"different": sorted(n for n in set(ours) & set(theirs) if abs(ours[n] - theirs[n]) > 0.005),
	}
