# SII: generación de registros, plazos, envío por el outbox de la capa AEAT,
# reenvío y cuadre (spec 14 §3-§4).

import json
import os
from typing import ClassVar

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, get_first_day, getdate, now_datetime, nowdate

from erpnext_spain.es_aeat.manager import AEATDriver
from erpnext_spain.es_sii import records
from erpnext_spain.es_sii.setup import MANUAL
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


# --- periodo y momento del envío ---------------------------------------------------------


def company_settings(company: str):
	return frappe.get_cached_value(
		"Company",
		company,
		["es_sii_activation_date", "es_sii_end_date", "es_sii_strategy", "es_sii_wait_days"],
		as_dict=True,
	)


def in_period(doc) -> bool:
	"""La fecha de registro contable está entre el inicio y el fin en el SII."""
	conf = company_settings(doc.company)
	posting_date = getdate(doc.posting_date)
	if conf.es_sii_activation_date and posting_date < getdate(conf.es_sii_activation_date):
		return False
	return not (conf.es_sii_end_date and posting_date > getdate(conf.es_sii_end_date))


def send_on(company: str, communication: str, posting_date, limit, wait_days: int | None = None) -> object:
	"""Desde cuándo puede enviarlo el trabajo programado: altas, a los días hábiles
	de espera desde el registro contable sin pasar del plazo legal; modificaciones
	y bajas, el mismo día."""
	if communication != records.NEW:
		return getdate(nowdate())
	days = cint(company_settings(company).es_sii_wait_days if wait_days is None else wait_days)
	return min(add_working_days(posting_date, days), getdate(limit))


def recompute_send_on(company: str, wait_days: int) -> None:
	"""Altas pendientes tras cambiar los días de espera de la compañía."""
	for row in frappe.get_all(
		"ES Sii Record",
		filters={"company": company, "status": PENDING, "communication": records.NEW},
		fields=["name", "voucher_type", "voucher_no", "deadline"],
	):
		posting_date = frappe.db.get_value(row.voucher_type, row.voucher_no, "posting_date")
		if posting_date:
			frappe.db.set_value(
				"ES Sii Record",
				row.name,
				"send_on",
				send_on(company, records.NEW, posting_date, row.deadline, wait_days),
				update_modified=False,
			)


# --- generación ------------------------------------------------------------------------


def new_record(doc, communication: str, content: dict, previous=None) -> str:
	book = BOOKS[doc.doctype]
	identification = content["IDFactura"]
	issuer = identification["IDEmisorFactura"]
	limit = deadline(book, doc.posting_date if communication != records.CANCEL else now_datetime())
	record = frappe.get_doc(
		{
			"doctype": "ES Sii Record",
			"company": doc.company,
			"book": book,
			"voucher_type": doc.doctype,
			"voucher_no": doc.name,
			"communication": communication,
			"status": PENDING,
			"deadline": limit,
			"send_on": send_on(doc.company, communication, doc.posting_date, limit),
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
	if not is_sii_active(doc.company) or not in_period(doc):
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


# Dirección del servicio por libro y entorno: campo de ES Settings y valor oficial
# (el de los WSDL incluidos en la app) si el campo está vacío.
ENDPOINTS: dict[tuple[str, str], tuple[str, str]] = {
	(records.ISSUED, "pruebas"): (
		"sii_issued_url_test",
		"https://www7.aeat.es/wlpl/SSII-FACT/ws/fe/SiiFactFEV1SOAP",
	),
	(records.ISSUED, "produccion"): (
		"sii_issued_url_production",
		"https://www1.agenciatributaria.gob.es/wlpl/SSII-FACT/ws/fe/SiiFactFEV1SOAP",
	),
	(records.RECEIVED, "pruebas"): (
		"sii_received_url_test",
		"https://www7.aeat.es/wlpl/SSII-FACT/ws/fr/SiiFactFRV1SOAP",
	),
	(records.RECEIVED, "produccion"): (
		"sii_received_url_production",
		"https://www1.agenciatributaria.gob.es/wlpl/SSII-FACT/ws/fr/SiiFactFRV1SOAP",
	),
}


def endpoint(book: str, environment: str) -> str:
	field, official = ENDPOINTS[(book, environment)]
	return (frappe.get_cached_doc("ES Settings").get(field) or "").strip() or official


class SiiClient:
	"""Cliente SOAP del SII: un WSDL por libro (expedidas y recibidas) y la
	dirección del servicio de ES Settings."""

	PORTS: ClassVar[dict[tuple[str, str], str]] = {
		(records.ISSUED, "pruebas"): "SuministroFactEmitidasPruebas",
		(records.ISSUED, "produccion"): "SuministroFactEmitidas",
		(records.RECEIVED, "pruebas"): "SuministroFactRecibidasPruebas",
		(records.RECEIVED, "produccion"): "SuministroFactRecibidas",
	}

	def __init__(self, company: str, environment: str):
		from erpnext_spain.es_aeat.client import enabled_credential_pem_paths

		self.company = company
		self.environment = environment
		self.cert_pem, self.key_pem = enabled_credential_pem_paths(company, SERVICE)
		self.clients = {}

	def send(self, payload: dict) -> dict:
		import requests
		from zeep import helpers

		from erpnext_spain.es_aeat.client import load_wsdl_client

		book = payload["book"]
		if book not in self.clients:
			session = requests.Session()
			session.cert = (self.cert_pem, self.key_pem)
			path = os.path.join(
				frappe.get_app_path("erpnext_spain", "schemas", "aeat", "sii"), records.WSDL[book]
			)
			client = load_wsdl_client(
				path,
				session=session,
				service_name="siiService",
				port_name=self.PORTS[(book, self.environment)],
			)
			binding = next(name for name in client.wsdl.bindings if name.endswith("}siiBinding"))
			self.clients[book] = client.create_service(binding, endpoint(book, self.environment))
		response = getattr(self.clients[book], payload["operacion"])(**payload["datos"])
		return dict(helpers.serialize_object(response, dict))


class SiiDriver(AEATDriver):
	service = SERVICE

	def __init__(self, client: object | None = None, selected: list[str] | None = None):
		"""`selected`: envío manual de esos registros (sin mirar la estrategia ni la
		fecha de envío). Sin él, el trabajo programado: compañías en automático y
		registros con «Enviar a partir del» cumplido."""
		self.client = client
		self.selected = selected

	def get_companies(self) -> list[str]:
		return frappe.get_all("ES Sii Record", filters=self.due_filters(), pluck="company", distinct=True)

	def due_filters(self, company: str | None = None) -> dict:
		filters = {"status": PENDING}
		if company:
			filters["company"] = company
		if self.selected is not None:
			filters["name"] = ["in", self.selected or [""]]
		return filters

	def due_or_filters(self, company: str) -> list | None:
		if self.selected is not None:
			return None
		# Registros anteriores a esta versión no tienen fecha de envío: se envían.
		return [["send_on", "<=", nowdate()], ["send_on", "is", "not set"]]

	def get_pending(self, company: str) -> list:
		if self.selected is None and company_settings(company).es_sii_strategy == MANUAL:
			return []
		filters, or_filters = self.due_filters(company), self.due_or_filters(company)
		first = frappe.get_all(
			"ES Sii Record",
			filters=filters,
			or_filters=or_filters,
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
			filters={**filters, "book": book, "communication": ["in", communications]},
			or_filters=or_filters,
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
		from erpnext_spain.es_sii import notices

		counts: dict[str, int] = {}
		company = None
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
			counts[status] = counts.get(status, 0) + 1
			company = record.company
		if company:
			notices.notify_results(company, counts)

	def rate_limit_seconds(self, company: str) -> int:
		return 0

	def on_batch_failure(self, company: str, pending: list, error: Exception) -> None:
		for record in pending:
			frappe.db.set_value(
				"ES Sii Record", record.name, {"error_description": f"{error!r}"[:500]}, update_modified=False
			)


def drain_outbox() -> None:
	"""Job programado: envía los registros pendientes de las compañías con envío
	automático cuya fecha de envío ya ha llegado."""
	from erpnext_spain.es_aeat.manager import AEATOutboxManager

	AEATOutboxManager().drain([SiiDriver()])


# --- envío manual ----------------------------------------------------------------------------

MANUAL_QUEUE_ABOVE = 50


@frappe.whitelist(methods=["POST"])
def send_invoices(doctype: str, names: list | str) -> dict:
	"""Acción «Enviar al SII» de las listas de facturas: envía ya los registros
	pendientes de las facturas seleccionadas (en segundo plano si son muchas)."""
	from erpnext_spain.es_facturacion.bulk import as_list

	if doctype not in BOOKS:
		frappe.throw(_("Solo se envían al SII facturas de venta y de compra."))
	check_role()
	names = as_list(names)
	for name in names:
		frappe.get_doc(doctype, name).check_permission("write")
	pending = frappe.get_all(
		"ES Sii Record",
		filters={"voucher_type": doctype, "voucher_no": ["in", names], "status": PENDING},
		pluck="name",
	)
	if not pending:
		frappe.throw(
			_(
				"Ninguna de las facturas seleccionadas tiene registros del SII pendientes de envío."
				" Revise que la compañía tenga el SII activado y que la fecha de registro contable"
				" esté dentro del periodo del SII."
			)
		)
	if len(pending) > MANUAL_QUEUE_ABOVE:
		frappe.enqueue("erpnext_spain.es_sii.outbox.send_records", queue="long", records=pending)
		return {"queued": True, "count": len(pending)}
	return send_records(pending)


def send_records(records_to_send: list[str]) -> dict:
	"""Envía esos registros pendientes, por lotes de un mismo libro y tipo de
	comunicación, y devuelve el estado final de cada uno."""
	from erpnext_spain.es_aeat.manager import AEATOutboxManager

	manager, driver = AEATOutboxManager(), SiiDriver(selected=list(records_to_send))
	# Cada pasada envía un lote por compañía; como mucho, uno por cada registro.
	for _attempt in range(len(records_to_send)):
		before = frappe.db.count("ES Sii Record", {"name": ["in", records_to_send], "status": PENDING})
		if not before:
			break
		manager.drain([driver])
		if frappe.db.count("ES Sii Record", {"name": ["in", records_to_send], "status": PENDING}) == before:
			break  # sin avances (error de conexión ya registrado)
	return dict(
		frappe.get_all(
			"ES Sii Record",
			filters={"name": ["in", records_to_send]},
			fields=["name", "status"],
			as_list=True,
		)
	)


# --- avisos de plazo y cuadre ----------------------------------------------------------------


def warn_deadlines() -> None:
	"""Job diario: registros pendientes o incorrectos que vencen hoy, mañana o ya vencidos."""
	from erpnext_spain.es_sii import notices

	limit = add_days(nowdate(), 1)
	filters = {"status": ["in", [PENDING, WRONG]], "deadline": ["<=", limit]}
	for company in frappe.get_all("ES Sii Record", filters=filters, pluck="company", distinct=True):
		count = frappe.db.count("ES Sii Record", {**filters, "company": company})
		notices.notify(
			company,
			_("SII de {0}: {1} registros vencen hoy, mañana o ya han vencido.").format(company, count),
			_("Revise los registros del SII pendientes o rechazados y envíelos antes del plazo."),
			notices.RED,
		)


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
