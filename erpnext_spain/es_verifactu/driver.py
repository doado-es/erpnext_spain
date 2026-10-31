# Driver VeriFactu del AEATOutboxManager (lote 5a, spec 04 §8 + spec 13 §5).
#
# Conecta el libro de registros («ES Verifactu Billing Record») con el
# drenaje genérico del manager: aporta (a) las empresas con pendientes —
# SIN gate de «activada» (spec 04 §8: lo pendiente al desactivar sigue
# remitiéndose, igual que las anulaciones), (b) los registros PendienteEnvio
# ORDENADOS por chain_index y limitados por el lote de la empresa, (c) el
# payload wire SOAP (Cabecera + RegistroFactura, forma de la referencia
# `spanish_compliance/.../aeat_data_adapter.py` validada contra el entorno
# de pruebas de la AEAT), (d) el cliente (entorno según el modo operativo
# de la empresa, TLS con los PEM de su credencial) y (e) el procesador de
# respuestas: transiciona los estados del libro por la VÍA SANCIONADA
# (flag del procesador, spec 04 §3) y denormaliza el estado de la factura
# con el mapper de emission.py.
#
# La persistencia de la respuesta (ES AEAT Response + líneas) la hace el
# MANAGER (persist_response): el driver solo la CONSUME.
#
# Forma wire (espejo de la referencia, byte-exacta en claves y anidación):
#   {"operacion": "RegFactuSistemaFacturacion",
#    "datos": {"Cabecera": {"ObligadoEmision": {NombreRazon, NIF}},
#              "RegistroFactura": [ {RegistroAlta|RegistroAnulacion: {
#                  IDFactura, RefExterna=<docname del libro>,
#                  Encadenamiento, ...campos del record_json} }]}}
#
# El record_json del libro es PLANO (contrato congelado del lote 4a: la
# huella viaja sobre esa forma): el driver anida IDFactura y construye el
# Encadenamiento (PrimerRegistro | RegistroAnterior con la identidad y
# huella del predecesor de la cadena) a partir de él y del propio libro.

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import cint

from erpnext_spain.aeat.client import ENV_PRODUCTION, ENV_TEST
from erpnext_spain.aeat.manager import AEATDriver
from erpnext_spain.aeat.tests.mock_aeat_client import build_client
from erpnext_spain.es_verifactu.doctype.es_verifactu_billing_record.es_verifactu_billing_record import (
	LEDGER_DOCTYPE,
	PENDING_SEND_STATE,
	RESPONSE_PROCESSOR_FLAG,
	TERMINAL_STATES,
)
from erpnext_spain.es_verifactu.emission import (
	INVOICE_STATUS_BY_LEDGER,
	get_sif_data,
)
from erpnext_spain.es_verifactu.error_strategy import RESUBMITTABLE_STATES, apply_strategy

# Operación SOAP de remisión de lotes de registros (WSDL VeriFactu).
REGFACTU_OPERATION = "RegFactuSistemaFacturacion"

# Modos operativos de la Company (spec 04 §2.3) → entorno AEAT del cliente.
PRODUCTION_MODE = "Producción"

# Valores por defecto de los settings de la Company (setup.py) si la fila
# viniera vacía: 60 s de espera entre envíos, 1000 registros (tope AEAT).
RATE_LIMIT_DEFAULT = 60
BATCH_LIMIT_DEFAULT = 1000

LEDGER_FIELDS = [
	"name",
	"company",
	"sales_invoice",
	"record_type",
	"invoice_type",
	"chain_index",
	"record_json",
	"hash",
	"previous_hash",
	"status",
]


class VerifactuDriver(AEATDriver):
	"""Driver del outbox VeriFactu para el AEATOutboxManager (spec 13 §5)."""

	service = "VeriFactu"

	def __init__(self, client_factory: Any = None):
		"""`client_factory` inyectable para tests (mismo contrato que
		mock_aeat_client.build_client: service/environment/company → cliente
		con .send(payload) → dict). Por defecto, la factory conmutada por el
		flag del site `es_aeat_mock` (cliente real sin flag)."""
		self.client_factory = client_factory or build_client

	# --- outbox (spec 04 §8) ------------------------------------------------

	def get_companies(self) -> list[str]:
		"""Empresas con registros PendienteEnvio (DISTINCT, ORM). NÓTESE: sin
		gate de «activada» (spec 04 §8) — el drenaje no depende del flag."""
		return frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"status": PENDING_SEND_STATE},
			pluck="company",
			distinct=True,
			order_by="company asc",
		)

	def get_pending(self, company: str) -> list[Any]:
		"""Registros PendienteEnvio de la empresa, ORDENADOS por chain_index
		(orden legal de la cadena) y limitados por el lote de la empresa (el
		manager recorta además a su propio tope: defensa en profundidad)."""
		return frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"company": company, "status": PENDING_SEND_STATE},
			fields=LEDGER_FIELDS,
			order_by="chain_index asc",
			limit_page_length=self.batch_limit(company),
		)

	# --- payload wire --------------------------------------------------------

	def build_payload(self, company: str, records: list[Any]) -> dict:
		"""Payload estructurado del manager: {"operacion", "datos"} con la
		Cabecera (ObligadoEmisión de la Company) y los RegistroFactura
		anidados desde el record_json plano del libro."""
		company_conf = frappe.db.get_value("Company", company, ["company_name", "tax_id"], as_dict=True)
		predecessors = self._predecessors(company, records)
		return {
			"operacion": REGFACTU_OPERATION,
			"datos": {
				"Cabecera": {
					"ObligadoEmision": {
						"NombreRazon": company_conf.company_name,
						"NIF": company_conf.tax_id,
					}
				},
				"RegistroFactura": [
					self._wire_record(record, predecessors, company, company_conf) for record in records
				],
			},
		}

	def _wire_record(
		self, record: Any, predecessors: dict[int, Any], company: str, company_conf: Any
	) -> dict:
		"""Un elemento RegistroFactura: {tipo_registro: interior} con el
		record_json plano ANIDADO (IDFactura + Encadenamiento + campos AEAT).
		RefExterna = docname del registro del libro: es la llave por la que
		las RespuestaLinea de la AEAT (y las líneas sintéticas de Fault)
		vuelven a SU registro (patrón de la referencia).

		Interior COMPLETO que exige el WSDL (fix del drenaje en vivo: a la
		AEAT le faltaba Required element NombreRazonEmisor): el record_json
		es la fuente de verdad y el wire PREFIERE sus valores — solo
		FALLA A ENRIQUECER para las claves que le faltan (record_json del
		formato anterior, p. ej. los pendientes creados antes del fix):
		NombreRazonEmisor de la Company (la de la Cabecera), SistemaInformatico
		por get_sif_data, Destinatarios desde el cliente de la
		factura enlazada, DescripcionOperacion y flags "N"/"N"/"N". El
		record_json NO se toca (spec 04 §2.2: lo remitido es lo registrado).
		"""
		data = _parse_json(record.record_json)
		chain = self._build_chain(record, data, predecessors)

		if record.record_type == "RegistroAnulacion":
			interior = {
				"IDFactura": {
					"IDEmisorFacturaAnulada": data["IDEmisorFacturaAnulada"],
					"NumSerieFacturaAnulada": data["NumSerieFacturaAnulada"],
					"FechaExpedicionFacturaAnulada": data["FechaExpedicionFacturaAnulada"],
				},
				"RefExterna": record.name,
				"RechazoPrevio": data.get("RechazoPrevio") or "N",
				"SinRegistroPrevio": data.get("SinRegistroPrevio") or "N",
				"SistemaInformatico": data.get("SistemaInformatico") or get_sif_data(company),
				"Encadenamiento": chain,
				"FechaHoraHusoGenRegistro": data["FechaHoraHusoGenRegistro"],
				"TipoHuella": data["TipoHuella"],
				"Huella": data["Huella"],
				"IDVersion": data["IDVersion"],
			}
			return {"RegistroAnulacion": interior}

		interior = {
			"IDFactura": {
				"IDEmisorFactura": data["IDEmisorFactura"],
				"NumSerieFactura": data["NumSerieFactura"],
				"FechaExpedicionFactura": data["FechaExpedicionFactura"],
			},
			"RefExterna": record.name,
			"DescripcionOperacion": data.get("DescripcionOperacion")
			or _legacy_operation_description(record, data),
			"TipoFactura": data["TipoFactura"],
		}
		# Opcionales del Alta solo si el registro los lleva (rectificativas).
		if "TipoRectificativa" in data:
			interior["TipoRectificativa"] = data["TipoRectificativa"]
		if "FacturasRectificadas" in data:
			interior["FacturasRectificadas"] = data["FacturasRectificadas"]
		interior["NombreRazonEmisor"] = data.get("NombreRazonEmisor") or company_conf.company_name
		interior["Subsanacion"] = data.get("Subsanacion") or "N"
		interior["RechazoPrevio"] = data.get("RechazoPrevio") or "N"
		# OJO: SinRegistroPrevio es campo del tipo ANULACIÓN del WSDL
		# (RegistroFacturacionBajaType) — NO existe en RegistroFacturacionAltaType
		# (verificado en vivo contra SuministroInformacion.xsd: zeep lo rechaza con
		# «unexpected keyword argument»). Jamás anexarlo al Alta.
		recipients = data.get("Destinatarios") or _legacy_recipients(record)
		if recipients:
			interior["Destinatarios"] = recipients
		interior["Desglose"] = _wire_tax_breakdown(data["Desglose"])
		interior["CuotaTotal"] = data["CuotaTotal"]
		interior["ImporteTotal"] = data["ImporteTotal"]
		interior["SistemaInformatico"] = data.get("SistemaInformatico") or get_sif_data(company)
		interior["Encadenamiento"] = chain
		interior["FechaHoraHusoGenRegistro"] = data["FechaHoraHusoGenRegistro"]
		interior["TipoHuella"] = data["TipoHuella"]
		interior["Huella"] = data["Huella"]
		interior["IDVersion"] = data["IDVersion"]
		return {"RegistroAlta": interior}

	def _build_chain(self, record: Any, data: dict, predecessors: dict[int, Any]) -> dict:
		"""Encadenamiento wire (espejo de _get_encadenamiento_values de la
		referencia): PrimerRegistro=S para el primero de la cadena;
		RegistroAnterior={IDFactura del predecesor, Huella} para el resto.
		El predecesor puede estar en el MISMO lote (cadena de pendientes)."""
		if data.get("PrimerRegistro") == "S":
			return {"PrimerRegistro": "S"}

		previous = predecessors.get(cint(record.chain_index) - 1)
		if previous is None:
			# No debería ocurrir (chain_index consecutivo base 1 bajo cerrojo):
			# una cadena rota NO se remite (la AEAT rechazaría el lote entero).
			# El error PROPAGA al aislamiento por empresa del manager.
			frappe.throw(
				f"Cadena rota en {self.service}: el registro {record.name} de"
				f" {record.company} (posición {record.chain_index}) no"
				" tiene predecesor en el libro y no se puede construir su"
				" Encadenamiento. Remedio: no elimine registros del libro"
				" manualmente (es historia legal inmutable, spec 04 §2.2);"
				" restaure el registro anterior o repare la cadena antes de"
				" volver a remitir.",
				frappe.ValidationError,
			)

		previous_data = _parse_json(previous.record_json)
		if previous.record_type == "RegistroAnulacion":
			identification = {
				"IDEmisorFactura": previous_data["IDEmisorFacturaAnulada"],
				"NumSerieFactura": previous_data["NumSerieFacturaAnulada"],
				"FechaExpedicionFactura": previous_data["FechaExpedicionFacturaAnulada"],
			}
		else:
			identification = {
				"IDEmisorFactura": previous_data["IDEmisorFactura"],
				"NumSerieFactura": previous_data["NumSerieFactura"],
				"FechaExpedicionFactura": previous_data["FechaExpedicionFactura"],
			}
		return {"RegistroAnterior": {**identification, "Huella": previous.hash}}

	def _predecessors(self, company: str, records: list[Any]) -> dict[int, Any]:
		"""chain_index → registro previo (una lectura indexada por lote):
		solo se buscan los predecesores de los registros ENCADENADOS
		(PrimerRegistro=N) — el primero de la cadena no gasta lectura."""
		wanted = {
			cint(record.chain_index) - 1
			for record in records
			if _parse_json(record.record_json).get("PrimerRegistro") != "S"
		}
		if not wanted:
			return {}
		rows = frappe.get_all(
			LEDGER_DOCTYPE,
			filters={"company": company, "chain_index": ("in", sorted(wanted))},
			fields=["name", "record_type", "chain_index", "record_json", "hash"],
		)
		return {row.chain_index: row for row in rows}

	# --- envío y cliente ------------------------------------------------------

	def get_client(self, company: str) -> Any:
		"""Cliente AEAT (VeriFactu) de la empresa: entorno según su modo
		operativo (Pruebas/Producción, spec 04 §2.3); la TLS mutua con los
		PEM de su credencial la resuelve la factory (errores de construcción
		quedan aislados por empresa en el manager, sin reintento)."""
		mode = frappe.db.get_value("Company", company, "es_verifactu_test_mode")
		return self.client_factory(
			service=self.service,
			environment=ENV_PRODUCTION if mode == PRODUCTION_MODE else ENV_TEST,
			company=company,
		)

	# --- procesamiento de la respuesta (spec 04 §3) --------------------------

	def process_response(self, response: dict, response_doc: Any) -> None:
		"""Consume las RespuestaLinea (y las sintéticas de SOAP Fault, misma
		forma): por RefExterna → SU registro del libro → transición terminal
		BAJO EL FLAG del procesador (única vía sancionada, spec 04 §3) +
		enlace a la respuesta + código/mensaje de error; y denormaliza el
		estado de la factura con el mapper de emission.py.

		Las líneas de ANULACIÓN se procesan IGUAL (el RegistroAnulacion es un
		registro del libro con su propia RefExterna). Una línea desconocida o
		sin estado no rompe el lote: se registra y se continúa (spec 13 §5:
		el procesador jamás lanza si puede evitarlo)."""
		for line in response.get("RespuestaLinea") or []:
			if not isinstance(line, dict):
				continue
			self._process_line(line, response_doc)

	def _process_line(self, line: dict, response_doc: Any) -> None:
		ref = line.get("RefExterna")
		state = line.get("EstadoRegistro")

		if not ref or state not in TERMINAL_STATES:
			frappe.log_error(
				title=f"AEAT {self.service}: línea de respuesta ilegible",
				message=(
					f"Línea sin RefExterna o sin EstadoRegistro terminal"
					f" (estado={state!r}) en la respuesta"
					f" {getattr(response_doc, 'name', '?')}:\n{frappe.as_json(line)}"
				),
			)
			return

		if not frappe.db.exists(LEDGER_DOCTYPE, ref):
			frappe.log_error(
				title=f"AEAT {self.service}: respuesta con ref desconocida",
				message=(
					f"La línea remite {ref!r} que no existe en el libro de"
					f" registros (respuesta {getattr(response_doc, 'name', '?')})."
					" La AEAT podría estar respondiendo a una remisión"
					" anterior a una restauración del libro:\n"
					f"{frappe.as_json(line)}"
				),
			)
			return

		record = frappe.get_doc(LEDGER_DOCTYPE, ref)
		code = line.get("CodigoErrorRegistro")
		description = line.get("DescripcionErrorRegistro")
		response_name = str(response_doc.name)  # autoincrement llega como int

		# Idempotencia por respuesta (lote 5b, spec 04 §9): reprocesar la
		# MISMA respuesta (reenvío duplicado, replay de grabación) NO vuelve
		# a transicionar ni a disparar la estrategia de errores — un
		# reintento re-procesado duplicaría registros del libro.
		if str(record.response or "") == response_name and record.status == state:
			return

		# Transición terminal por la VÍA SANCIONADA (spec 04 §3): el flag
		# habilita al procesador a tocar el libro (nadie más lo fija).
		# flags.ignore_links: el libro es HISTORIA LEGAL que sobrevive a
		# CUALQUIER operación sobre la factura (spec 04 §2.2) — la factura
		# puede haber sido borrada tras la emisión y la transición DEBE
		# persistar igual (verificado en vivo: un link muerto tumbaba el
		# procesado entero y el rollback se llevaba la respuesta consigo →
		# loop de reenvíos). NÓTESE el kwarg save(ignore_links=) de Document
		# revienta en _save (v16) — el flag directo es la vía (document.py
		# 466-467/1209).
		record.flags[RESPONSE_PROCESSOR_FLAG] = True
		record.flags.ignore_links = True
		record.status = state
		record.response = response_name
		record.response_error_code = str(code) if code not in (None, "") else None
		record.response_error_msg = description or None
		record.save(ignore_permissions=True)

		# Estado denormalizado de la FACTURA (mapper canónico de emission.py:
		# fija la denominación de los estados; las variantes de subsanación
		# llegan con el lote 5b). Combinaciones sin entrada (p. ej. Alta
		# Incorrecto) no tocan la factura: su estrategia es la subsanación.
		invoice_status = INVOICE_STATUS_BY_LEDGER.get(record.record_type, {}).get(state)
		if invoice_status and record.sales_invoice:
			frappe.db.set_value(
				"Sales Invoice",
				record.sales_invoice,
				"es_verifactu_status",
				invoice_status,
				update_modified=False,
			)

		# Estrategia por código de error (lote 5b, spec 04 §3/§9): cuando el
		# registro NO quedó Correcto y la línea trae código, el mapa decide
		# (reintento / subsanación automática / manual / desconocido). El
		# procesador jamás rompe el lote: apply_strategy aísla sus fallos
		# con log_error.
		if record.response_error_code and state in RESUBMITTABLE_STATES:
			apply_strategy(record.name, record.response_error_code, description)

	# --- parámetros por empresa (settings de la funcionalidad) ----------------

	def rate_limit_seconds(self, company: str) -> int:
		"""Espera mínima entre envíos de la empresa: su «Timeout de remisión»
		(scout: es_verifactu_timeout_seconds, default 60)."""
		return (
			cint(frappe.db.get_value("Company", company, "es_verifactu_timeout_seconds"))
			or RATE_LIMIT_DEFAULT
		)

	def batch_limit(self, company: str) -> int:
		"""Máximo de registros por lote (tope AEAT 1000): el campo de la
		Company (default 1000); el manager recorta además a su tope."""
		return (
			cint(frappe.db.get_value("Company", company, "es_verifactu_batch_limit")) or BATCH_LIMIT_DEFAULT
		)

	def on_batch_failure(self, company: str, records: list[Any], error: Exception) -> None:
		"""Tope de reintentos agotado (errores transitorios): los registros
		QUEDAN PendienteEnvio — visibles como pendientes — y el cron del
		minuto siguiente reintenta el lote (spec 04 §8/§13 §5). Se deja
		constancia auditable del lote afectado (el manager ya notificó)."""
		refs = [record.get("name") for record in records if isinstance(record, dict)]
		frappe.log_error(
			title=f"AEAT {self.service}: lote PendienteEnvio de {company}",
			message=(
				f"Tras agotar los reintentos ({error!r}) siguen PendienteEnvio"
				f" los registros {refs} de {company}: el planificador los"
				" reintentará en su próxima corrida."
			),
		)


def _parse_json(value: Any) -> dict:
	"""record_json del libro: str JSON desde la BD (o dict ya parseado)."""
	if isinstance(value, str):
		return json.loads(value)
	return value or {}


def _wire_tax_breakdown(breakdown: dict) -> dict:
	"""Desglose wire con el CHOICE del DetalleType vigente
	(SuministroInformacion.xsd): CalificacionOperacion | OperacionExenta —
	la causa de exención L10 viaja como VALOR de OperacionExenta (string
	E1–E8), nunca como CausaExenta plano junto a una calificación.
	Retrocompatible: los record_json anteriores al fix llevan la forma
	plana ({CalificacionOperacion, CausaExenta}) de un WSDL más antiguo —
	se reescriben aquí sin tocar el libro (la fuente de verdad queda
	como estaba; solo el wire cambia).
	"""
	if not breakdown or not breakdown.get("DetalleDesglose"):
		return breakdown
	rows = []
	for row in breakdown["DetalleDesglose"]:
		row = dict(row)
		cause = row.pop("CausaExenta", None)
		if cause:
			# forma legada → choice vigente (la calificación no acompaña)
			row.pop("CalificacionOperacion", None)
			row["OperacionExenta"] = cause
		if "OperacionExenta" in row:
			# Regla 1238 de la AEAT (verificada en vivo): operación exenta →
			# SIN TipoImpositivo ni CuotaRepercutida (los record_json previos
			# al fix las llevan — el record_json es historia inmutable, el
			# WIRE se corrige aquí).
			row.pop("TipoImpositivo", None)
			row.pop("CuotaRepercutida", None)
		rows.append(row)
	return {"DetalleDesglose": rows}


def _legacy_operation_description(record: Any, data: dict) -> str:
	"""DescripcionOperacion de un record_json del formato anterior (sin la
	clave): el texto de la referencia, desde la factura enlazada."""
	name = record.sales_invoice or data.get("NumSerieFactura") or record.name
	base_total = (
		frappe.db.get_value("Sales Invoice", record.sales_invoice, "base_total")
		if record.sales_invoice
		else None
	)
	if base_total is None:
		base_total = data.get("ImporteTotal", 0)
	return f"Factura {name} por cantidad {base_total}"


def _legacy_recipients(record: Any) -> dict | None:
	"""Destinatarios de un record_json del formato anterior: el cliente de
	la factura enlazada (SI.customer → Customer customer_name+tax_id). None
	sin factura, sin cliente o en venta POS (los tickets simplificados
	nacen sin destinatario, semántica de emission._recipient): el bloque
	NO viaja."""
	if not record.sales_invoice:
		return None
	invoice = frappe.db.get_value("Sales Invoice", record.sales_invoice, ["customer", "is_pos"], as_dict=True)
	if not invoice or not invoice.customer or invoice.is_pos:
		return None
	name, tax_id = frappe.db.get_value("Customer", invoice.customer, ["customer_name", "tax_id"])
	return {"IDDestinatario": [{"NombreRazon": name, "NIF": tax_id}]}
