# Mock grabar/reproducir del cliente AEAT para los tests de integración de
# VeriFactu y SII (spec 13, tarea 5).
#
# Semillas: los ejemplos reales de respuesta de la AEAT de la referencia
# (`spanish_compliance/.../aeat_response_examples/`), convertidos a JSON en
# tests/data con las fechas serializadas — exactamente la forma que devuelve
# AEATClient.send tras helpers.serialize_object + json.dumps(default=str).
#
# Uso:
# - Tests unitarios: inyectar `mock_client_factory` en AEATClient (nivel zeep:
#   un objeto con `.service.<operacion>` que devuelve dicts o lanza Fault) o
#   usar MockAEATClient directamente (nivel AEATClient: mismo contrato send).
# - Caminos de integración (lotes 04/05): el flag de configuración del site
#   `es_aeat_mock` («replay» o «record») hace que build_client() devuelva el
#   mock para TODOS los caminos de producción:
#     bench --site <site> set-config es_aeat_mock record   # grabar contra AEAT pruebas
#     bench --site <site> set-config es_aeat_mock replay   # reproducir sin certificado
#     bench --site <site> clear-config es_aeat_mock        # cliente real

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frappe

DATA_DIR = Path(__file__).parent / "data"
RECORDINGS_DIR = DATA_DIR / "recordings"

# Semillas por defecto (ejemplos reales de la referencia) por nombre.
SEEDS = {
	"alta_aceptada_con_errores": "alta_aceptada_con_errores.json",
	"registro_duplicado_incorrecto": "registro_duplicado_incorrecto.json",
}

ES_AEAT_MOCK_CONF = "es_aeat_mock"
MODES = ("record", "replay")


def load_seed(name: str) -> dict:
	"""Carga una respuesta semilla de tests/data (ejemplos reales AEAT)."""
	path = DATA_DIR / SEEDS[name]
	return json.loads(path.read_text(encoding="utf-8"))


def mock_mode() -> str | None:
	"""Modo de mock del site (config del bench): 'record' | 'replay' | None.

	Se lee de la config del site (bench set-config) y, en su defecto, de la
	common config del bench (bench set-config -g). Valor desconocido → replay
	(reproducir es siempre seguro: no toca la red).
	"""
	from frappe.config import get_common_site_config

	for conf in (frappe.conf, get_common_site_config()):
		if not conf:
			continue
		value = conf.get(ES_AEAT_MOCK_CONF)
		if value:
			return value if value in MODES else "replay"
	return None


def build_client(service: str, environment: str, company: str, **kwargs: Any):
	"""Factory conmutada por el flag del site: MockAEATClient o AEATClient real.

	Es la factory que usan los drivers en los caminos de producción: con el
	flag `es_aeat_mock` activo, TODA la integración va al mock (grabar contra
	el entorno de pruebas de la AEAT una vez, reproducir en CI sin certificado).
	"""
	mode = mock_mode()
	if mode:
		return MockAEATClient(service=service, environment=environment, company=company, mode=mode)
	from erpnext_spain.aeat.client import AEATClient

	return AEATClient(service=service, environment=environment, company=company, **kwargs)


class MockAEATClient:
	"""Reemplazo de AEATClient con el mismo contrato (send: payload → dict).

	- replay: devuelve la respuesta grabada que corresponda a la operación
	  del payload (mapa `responses` por operación, o una lista de respuestas
	  en cola por operación), o la primera semilla si no hay coincidencia.
	- record: envuelve un cliente real (`real_client`), graba cada
	  (payload, respuesta) en `recordings_dir` como JSON y devuelve la
	  respuesta tal cual.
	"""

	def __init__(
		self,
		*,
		service: str = "VeriFactu",
		environment: str = "pruebas",
		company: str | None = None,
		mode: str = "replay",
		responses: dict[str, Any] | None = None,
		real_client: Any = None,
		recordings_dir: Path | None = None,
		default_seed: str = "alta_aceptada_con_errores",
	):
		if mode not in MODES:
			frappe.throw(
				f"Modo de mock AEAT desconocido: {mode}. Remedio: use {' o '.join(MODES)}.",
				frappe.ValidationError,
			)
		if mode == "record" and real_client is None:
			frappe.throw(
				"El modo record de MockAEATClient exige un real_client que envolver"
				" (grabar = llamar al real y persistir su respuesta).",
				frappe.ValidationError,
			)

		self.service = service
		self.environment = environment
		self.company = company
		self.mode = mode
		self.responses = responses or {}
		self.real_client = real_client
		self.recordings_dir = Path(recordings_dir) if recordings_dir else RECORDINGS_DIR
		self.default_seed = default_seed
		self.sent_payloads: list[dict] = []
		self._recording_count = 0
		# Respuestas grabadas (replay): cola FIFO por operación, en orden de
		# grabación (prefijo numérico en el nombre del archivo).
		self._recorded_responses: dict[str, list[dict]] = {}
		if mode == "replay" and self.recordings_dir.exists():
			for path in sorted(self.recordings_dir.glob("*.json")):
				item = json.loads(path.read_text(encoding="utf-8"))
				operation = (item.get("payload") or {}).get("operacion")
				if operation:
					self._recorded_responses.setdefault(operation, []).append(item)

	def send(self, payload: dict) -> dict:
		self.sent_payloads.append(payload)
		if self.mode == "record":
			response = self.real_client.send(payload)
			self._record(payload, response)
			return response
		return self._replay(payload)

	# --- replay ---

	def _replay(self, payload: dict) -> dict:
		operation = payload.get("operacion")
		if operation in self.responses:
			response = self.responses[operation]
			# Cola de respuestas por operación (consumo FIFO) o respuesta única.
			if isinstance(response, list):
				if len(response) > 1:
					self.responses[operation] = response[1:]
					return response[0]
				return response[0]
			return response
		if operation in self._recorded_responses and self._recorded_responses[operation]:
			return self._recorded_responses[operation].pop(0)["respuesta"]
		return load_seed(self.default_seed)

	# --- record ---

	def _record(self, payload: dict, response: dict) -> None:
		self.recordings_dir.mkdir(parents=True, exist_ok=True)
		self._recording_count += 1
		operation = frappe.scrub(payload.get("operacion") or "operacion")
		path = self.recordings_dir / f"{operation}-{self._recording_count:04d}.json"
		path.write_text(
			json.dumps({"payload": payload, "respuesta": response}, indent=1, default=str),
			encoding="utf-8",
		)


class FakeZeepService:
	"""Imita `client.service.<operacion>` de zeep para inyectar en AEATClient
	via client_factory: devuelve dicts anidados (serialize_object los admite)
	o lanza la excepción configurada por operación."""

	def __init__(self, behaviors: dict[str, Any]):
		# operacion → dict (respuesta) | Exception (se lanza) | callable(payload_datos)
		self.behaviors = behaviors

	def __getattr__(self, operation: str):
		if operation not in self.behaviors:
			raise AttributeError(f"FakeZeepService: operación sin comportamiento: {operation}")

		behavior = self.behaviors[operation]

		def call(**data: Any):
			if isinstance(behavior, Exception) or (
				isinstance(behavior, type) and issubclass(behavior, Exception)
			):
				raise behavior
			if callable(behavior) and not isinstance(behavior, dict):
				return behavior(data)
			return behavior

		return call


def mock_client_factory(behaviors: dict[str, Any]):
	"""client_factory inyectable en AEATClient(...) que ignora WSDL/TLS y
	devuelve un cliente cuyo .service responde según `behaviors`."""

	def factory(**_kwargs: Any):
		client = frappe._dict()
		client["service"] = FakeZeepService(behaviors)
		return client

	return factory
