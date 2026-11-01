# AEATOutboxManager (spec 13 §5): drenaje por empresa del outbox de cada
# funcionalidad («drivers»: VeriFactu, SII), con rate-limit por empresa,
# espera AEAT fusionada, límite de lote, aislamiento TOTAL de errores y
# reintentos con backoff.
#
# El manager es genérico y NO conoce nada de negocio: los drivers registran su
# servicio en el dispatcher y aportan (a) los registros pendientes ORDENADOS,
# (b) el payload, (c) el envío, (d) el procesamiento de la respuesta y (e) los
# parámetros por empresa (timeout, lote, tope de reintentos), que viven en los
# settings de CADA funcionalidad — el driver los conoce, el manager no.
#
# Reloj y rate-limiter inyectables para tests deterministas. SIN commits
# explícitos: se respeta el ciclo transaccional del job (doc 12 §19).

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, ClassVar

import frappe
from frappe.utils import cint

from erpnext_spain.es_aeat.utils import notify_roles, now_aeat


class AEATClock:
	"""Reloj del sistema: inyectable en tests para rate-limit y backoff deterministas."""

	def now(self) -> datetime:
		return now_aeat()

	def sleep(self, seconds: float) -> None:
		time.sleep(seconds)


def _backoff_seconds(attempt: int, base: float = 2.0) -> float:
	"""Backoff exponencial simple: 2s, 4s, 8s... (spec 04 §8)."""
	return base * (2 ** (attempt - 1))


# Errores TRANSITORIOS de transporte que el manager reintenta con backoff.
# El resto (credencial ausente, config rota, bugs del driver) NO merece
# reintento: propaga al aislamiento por empresa del drain_driver, que lo
# registra con log_error y drena las demás empresas (spec 13 §5).
TRANSIENT_ERRORS = (ConnectionError, TimeoutError)


class AEATDriver(ABC):
	"""Interfaz que cada funcionalidad implementa para drenar su outbox con el
	manager genérico (spec 13 §5).

	Contratos:
	- `get_pending` devuelve registros ORDENADOS (la funcionalidad define el
	  orden legal, p. ej. chain_index) y JAMÁS fetch-all: pagina con
	  page_length y el manager recorta además a `batch_limit` (máx. AEAT 1000).
	- `send` recibe el cliente que `get_client` construyó y devuelve el dict
	  serializable de la respuesta (los SOAP Fault ya vienen convertidos a
	  líneas sintéticas). Errores de conexión PROPAGAN: el manager reintenta.
	- `process_response` consume las líneas por `external_ref` y transiciona
	  estados de SUS registros (jamás lanza si puede evitarlo: una respuesta
	  procesada con error de negocio queda aislada por empresa igualmente).
	"""

	service: ClassVar[str]  # p. ej. "VeriFactu" (llave del dispatcher y purpose de la credencial)

	@abstractmethod
	def get_companies(self) -> list[str]:
		"""Empresas con trabajo pendiente. NÓTESE (spec 04 §8): el drenaje no
		depende del flag «activada» de la funcionalidad — toda empresa con
		registros pendientes drena (lo pendiente al desactivar sigue remitiéndose)."""

	@abstractmethod
	def get_pending(self, company: str) -> list[Any]:
		"""Registros pendientes de la empresa, ORDENADOS y limitados por el driver."""

	@abstractmethod
	def build_payload(self, company: str, records: list[Any]) -> dict:
		"""Payload AEAT {"operacion": ..., "datos": {...}} para el lote."""

	@abstractmethod
	def get_client(self, company: str) -> Any:
		"""Cliente AEAT de la empresa (conoce el entorno pruebas/producción y
		la credencial del propósito del servicio). Errores de construcción
		quedan aislados por empresa en el manager (no se reintentan aquí)."""

	@abstractmethod
	def process_response(self, response: dict, response_doc: Any) -> None:
		"""Procesa la respuesta (líneas por external_ref) contra SUS registros."""

	def send(self, client: Any, payload: dict) -> dict:
		"""Envío del lote. Por defecto delega en el cliente tal cual (el
		cliente ya normaliza los SOAP Fault a líneas sintéticas); una
		funcionalidad lo redefine solo si su servicio lo exige."""
		return client.send(payload)

	def rate_limit_seconds(self, company: str) -> int:
		"""Espera mínima entre envíos de la empresa (settings de la funcionalidad)."""
		return 60

	def batch_limit(self, company: str) -> int:
		"""Máximo de registros por lote (AEAT permite hasta 1000)."""
		return 1000

	def max_attempts(self, company: str) -> int:
		"""Tope de intentos por lote antes de notificar el agotamiento."""
		return 3

	def on_batch_failure(self, company: str, records: list[Any], error: Exception) -> None:  # noqa: B027 (gancho opcional)
		"""Estado visible en los registros del driver tras agotar reintentos
		(spec 13 §5: notificación + estado visible)."""


class RateLimiter:
	"""Rate-limit por (servicio, empresa): espera `timeout_seconds` del driver
	entre envíos, FUSIONANDO el tiempo de espera que la propia AEAT devuelva
	(TiempoEsperaEnvio, >60s — spec 04 §8 / señalización del protocolo
	documentada en el roadmap de OCA l10n_es_verifactu_oca).

	El estado vive en la cache de Redis (compartida entre workers): es estado
	de control efímero, no de negocio — perderlo a lo sumo adelanta un envío.
	"""

	def __init__(self, service: str, clock: AEATClock | None = None):
		self.service = service
		self.clock = clock or AEATClock()

	def _key(self, company: str) -> str:
		return f"es_aeat_rate_limit:{self.service}:{company}"

	def allows(self, company: str) -> bool:
		next_allowed = frappe.cache().get_value(self._key(company))
		if not next_allowed:
			return True
		return self.clock.now() >= datetime.fromisoformat(next_allowed)

	def mark_sent(self, company: str, rate_limit_seconds: int, aeat_wait_seconds: int = 0) -> None:
		"""Marca el envío: el próximo envío de la empresa espera el máximo entre
		el rate-limit configurado y la espera pedida por la AEAT."""
		wait = max(cint(rate_limit_seconds), cint(aeat_wait_seconds))
		next_allowed = self.clock.now() + timedelta(seconds=wait)
		frappe.cache().set_value(self._key(company), next_allowed.isoformat(timespec="seconds"))


class AEATOutboxManager:
	"""Drenaje del outbox de todos los servicios con drivers registrados.

	Aislamiento TOTAL por empresa (spec 13 §5): cada empresa va en su propio
	try/except con `frappe.log_error` — un error JAMÁS aborta el run ni
	propaga (NUNCA frappe.throw dentro del bucle).
	"""

	def __init__(self, clock: AEATClock | None = None):
		self.clock = clock or AEATClock()

	def drain(self, drivers: Iterable[AEATDriver] | None = None) -> None:
		"""Drena los drivers dados (por defecto: todos los registrados en el
		dispatcher). Sin drivers: no-op silencioso (el driver de VeriFactu llega
		en su lote)."""
		for driver in drivers if drivers is not None else get_drivers():
			self.drain_driver(driver)

	def drain_driver(self, driver: AEATDriver) -> None:
		limiter = RateLimiter(driver.service, clock=self.clock)
		for company in driver.get_companies():
			try:
				self.drain_company(driver, company, limiter)
			except Exception:
				# Aislamiento total por empresa: log, siguiente empresa, jamás throw.
				frappe.log_error(
					title=f"AEAT {driver.service}: error drenando {company}",
					message=frappe.get_traceback(),
				)

	def drain_company(self, driver: AEATDriver, company: str, limiter: RateLimiter | None = None) -> None:
		"""Drena UNA empresa: rate-limit → lote ordenado → payload → envío con
		reintentos → persistencia de la respuesta → procesamiento → rate-limit."""
		limiter = limiter or RateLimiter(driver.service, clock=self.clock)
		if not limiter.allows(company):
			return

		records = driver.get_pending(company)
		if not records:
			return

		# Lote: el driver pagina, el manager garantiza el tope (defensa en
		# profundidad; el orden del driver se preserva).
		records = records[: driver.batch_limit(company)]
		payload = driver.build_payload(company, records)

		# La construcción del cliente (fetch del WSDL incluido) queda dentro del
		# aislamiento por empresa del drain_driver; no se reintenta aquí.
		client = driver.get_client(company)

		response = self._send_with_retries(driver, company, client, payload, records)
		if response is None:
			# Tope de reintentos agotado: ya notificado y con estado visible.
			return

		response_doc = persist_response(driver, company, payload, response)
		driver.process_response(response, response_doc)

		limiter.mark_sent(
			company,
			rate_limit_seconds=driver.rate_limit_seconds(company),
			aeat_wait_seconds=cint(response.get("TiempoEsperaEnvio") or 0),
		)

	def _send_with_retries(
		self,
		driver: AEATDriver,
		company: str,
		client: Any,
		payload: dict,
		records: list[Any],
	) -> dict | None:
		"""Envía con reintentos + backoff para errores transitorios de
		conexión; devuelve None al agotar el tope (notificación + estado
		visible + log). Los errores no transitorios PROPAGAN: el drain_driver
		los aísla por empresa sin gastar reintentos (reintentar «sin
		credencial» no lo arregla)."""
		limit = driver.max_attempts(company)
		last_error: Exception | None = None
		for attempt in range(1, limit + 1):
			try:
				return driver.send(client, payload)
			except TRANSIENT_ERRORS as e:
				last_error = e
				if attempt < limit:
					self.clock.sleep(_backoff_seconds(attempt))

		self._exhausted(driver, company, records, limit, last_error)
		return None

	def _exhausted(
		self,
		driver: AEATDriver,
		company: str,
		records: list[Any],
		limit: int,
		error: Exception | None,
	) -> None:
		frappe.log_error(
			title=f"AEAT {driver.service}: reintentos agotados para {company}",
			message=f"{limit} intentos fallidos. Último error:\n{error!r}\n\n{frappe.get_traceback()}",
		)
		driver.on_batch_failure(company, records, error)
		notify_roles(
			company,
			f"AEAT {driver.service}: reintentos de envío agotados",
			f"Se agotaron {limit} intentos de envío a la AEAT para la empresa"
			f" {company} ({driver.service}). Último error: {error}. Remedio:"
			" revise la conectividad y la credencial en «ES AEAT Credential», y"
			" verifique el estado de los registros pendientes; el drenaje"
			" reintentará en la próxima corrida del planificador.",
		)


# --- persistencia de la respuesta (normalización por servicio) ---

RESPONSE_PARSERS: dict[str, Any] = {
	"VeriFactu": "_parse_verifactu_response",
	# La respuesta del SII tiene la misma forma (EstadoEnvio, CSV, RespuestaLinea
	# con IDFactura y EstadoRegistro) (spec 14 §3).
	"SII": "_parse_verifactu_response",
}


def persist_response(driver: AEATDriver, company: str, payload: dict, response: dict):
	"""Normaliza la respuesta del servicio y la persiste en ES AEAT Response
	(+ líneas): crudo + parseado, auditable (spec 13 §3)."""
	parser_name = RESPONSE_PARSERS.get(driver.service)
	if not parser_name:
		frappe.throw(
			f"No hay parser de respuesta para el servicio {driver.service}."
			" Remedio: regístrelo en erpnext_spain.es_aeat.manager.RESPONSE_PARSERS.",
			frappe.ValidationError,
		)
	data = globals()[parser_name](response)

	doc = frappe.get_doc(
		{
			"doctype": "ES AEAT Response",
			"service": driver.service,
			"company": company,
			"request_payload": frappe.as_json(payload),
			"raw_response": frappe.as_json(response),
			"send_state": data["send_state"],
			"csv": data["csv"],
			"fault_code": data["fault_code"],
			"fault_message": data["fault_message"],
			"tiempo_espera_envio": data["tiempo_espera_envio"],
			"lines": data["lines"],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _parse_verifactu_response(response: dict) -> dict:
	"""Respuesta VeriFactu (y SOAP Faults sintéticos, misma forma) → campos del
	ES AEAT Response + líneas normalizadas por registro."""
	lines: list[dict] = []
	for line in response.get("RespuestaLinea") or []:
		if not isinstance(line, dict):
			continue
		operation = line.get("Operacion") or {}
		lines.append(
			{
				"external_ref": line.get("RefExterna"),
				"operation_type": operation.get("TipoOperacion"),
				"invoice_id": frappe.as_json(line.get("IDFactura") or {}),
				"record_state": line.get("EstadoRegistro"),
				"error_code": line.get("CodigoErrorRegistro"),
				"error_description": line.get("DescripcionErrorRegistro"),
				"duplicate_record": 1 if line.get("RegistroDuplicado") else 0,
				"subsanacion": 1 if operation.get("Subsanacion") else 0,
				"rechazo_previo": 1 if operation.get("RechazoPrevio") else 0,
				"sin_registro_previo": 1 if operation.get("SinRegistroPrevio") else 0,
			}
		)

	return {
		"send_state": response.get("EstadoEnvio"),
		"csv": response.get("CSV"),
		"fault_code": response.get("fault_code"),
		"fault_message": response.get("fault_message"),
		"tiempo_espera_envio": cint(response.get("TiempoEsperaEnvio") or 0),
		"lines": lines,
	}


# --- dispatcher por servicio (spec 13 §5) ---

_DRIVERS: dict[str, list[AEATDriver]] = {}


def register_driver(driver: AEATDriver) -> None:
	"""Registra un driver en el dispatcher por servicio. El scheduler (cron por
	minuto cuando exista el driver de VeriFactu) drena aquí todos los activos."""
	_DRIVERS.setdefault(driver.service, []).append(driver)


def get_drivers(service: str | None = None) -> list[AEATDriver]:
	"""Drivers registrados (todos, o los de un servicio). Lista vacía = no-op
	gracioso del drenaje (el driver de VeriFactu llega en su lote)."""
	if service is None:
		return [d for lista in _DRIVERS.values() for d in lista]
	return list(_DRIVERS.get(service, []))


def drain_all() -> None:
	"""Punto de entrada del scheduler: drena todos los servicios activos."""
	AEATOutboxManager().drain()
