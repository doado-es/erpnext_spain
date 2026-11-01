# Tests del AEATOutboxManager (spec 13 §5) con un driver MOCK y reloj
# inyectado: drenaje completo, rate-limit, espera AEAT fusionada, límite de
# lote, aislamiento por empresa y reintentos con backoff + tope.

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_aeat.manager import AEATDriver, AEATOutboxManager, get_drivers, register_driver
from erpnext_spain.es_aeat.tests.helpers import test_company
from erpnext_spain.es_aeat.utils import now_aeat

GHOST_COMPANY = "ES Empresa Fantasma AEAT"  # no existe: errores aislados


class FakeClock:
	"""Reloj inyectable: now() fijo, sleep() registra y AVANZA el reloj."""

	def __init__(self):
		self._now = now_aeat()
		self.sleeps: list[float] = []

	def now(self):
		return self._now

	def sleep(self, seconds: float) -> None:
		self.sleeps.append(seconds)
		self._now = self._now + timedelta(seconds=seconds)


class FakeClient:
	"""Cliente AEAT de mentira: respuestas en cola (FIFO) o excepciones."""

	def __init__(self, responses: list | None = None, error: Exception | None = None):
		self.responses = list(responses or [])
		self.error = error
		self.calls = 0
		self.payloads: list[dict] = []

	def send(self, payload: dict) -> dict:
		self.calls += 1
		self.payloads.append(payload)
		if self.error:
			raise self.error
		if self.responses:
			return self.responses.pop(0)
		raise RuntimeError("FakeClient sin respuestas configuradas")


def ok_response(refs: list[str], wait_seconds: int = 0) -> dict:
	"""Respuesta AEAT sintética: una línea Correcto por external_ref."""
	return {
		"CSV": "A-TESTCSV",
		"EstadoEnvio": "Correcto",
		"TiempoEsperaEnvio": str(wait_seconds),
		"RespuestaLinea": [
			{
				"IDFactura": {
					"IDEmisorFactura": "12345678Z",
					"NumSerieFactura": ref,
					"FechaExpedicionFactura": "30-01-2026",
				},
				"Operacion": {
					"TipoOperacion": "Alta",
					"Subsanacion": None,
					"RechazoPrevio": None,
					"SinRegistroPrevio": None,
				},
				"RefExterna": ref,
				"EstadoRegistro": "Correcto",
				"CodigoErrorRegistro": None,
				"DescripcionErrorRegistro": None,
				"RegistroDuplicado": None,
			}
			for ref in refs
		],
	}


class MockDriver(AEATDriver):
	"""Driver completo de mentira: registra TODO lo que el manager le pide."""

	service = "VeriFactu"

	def __init__(self, companies: list[str], records: list[dict] | None = None):
		self.companies = companies
		self.records = records or [{"name": "BR-001"}, {"name": "BR-002"}]
		self.clients: dict[str, FakeClient] = {}
		self.payloads: list[tuple[str, list]] = []
		self.processed: list[tuple[dict, object]] = []
		self.batch_failures: list[tuple[str, list, Exception]] = []
		self.rate_limit = 60
		self.batch = 1000
		self.attempt_limit = 3

	def get_companies(self) -> list[str]:
		return list(self.companies)

	def get_pending(self, company: str) -> list:
		return list(self.records)

	def build_payload(self, company: str, records: list) -> dict:
		self.payloads.append((company, [r["name"] for r in records]))
		return {
			"operacion": "RegFactuSistemaFacturacion",
			"datos": {
				"Cabecera": {"ObligadoEmision": {"NombreRazon": company, "NIF": "12345678Z"}},
				"RegistroFactura": [
					{"RegistroAlta": {"RefExterna": r["name"], "IDFactura": {"NumSerieFactura": r["name"]}}}
					for r in records
				],
			},
		}

	def get_client(self, company: str):
		return self.clients[company]

	def process_response(self, response: dict, response_doc) -> None:
		self.processed.append((response, response_doc))

	def rate_limit_seconds(self, company: str) -> int:
		return self.rate_limit

	def batch_limit(self, company: str) -> int:
		return self.batch

	def max_attempts(self, company: str) -> int:
		return self.attempt_limit

	def on_batch_failure(self, company: str, records: list, error: Exception) -> None:
		self.batch_failures.append((company, records, error))


class TestAEATOutboxManager(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()

	def setUp(self):
		frappe.cache().delete_keys("es_aeat_rate_limit:*")

	def _assert_response_persisted(self, doc, company: str, refs: list[str]):
		doc.reload()
		self.assertEqual(doc.service, "VeriFactu")
		self.assertEqual(doc.company, company)
		self.assertEqual(doc.send_state, "Correcto")
		self.assertEqual(doc.csv, "A-TESTCSV")
		self.assertEqual(doc.tiempo_espera_envio, 90)
		frappe.json.loads(doc.request_payload)
		frappe.json.loads(doc.raw_response)
		self.assertEqual([l.external_ref for l in doc.lines], refs)
		self.assertEqual(doc.lines[0].record_state, "Correcto")
		self.assertEqual(doc.lines[0].operation_type, "Alta")

	def test_full_drain_pending_payload_send_response(self):
		"""Drain completo: pending → payload ORDENADO → send → persistencia →
		process_response, con la respuesta cruda y sus líneas normalizadas."""
		refs = ["BR-001", "BR-002"]
		client = FakeClient(responses=[ok_response(refs, wait_seconds=90)])
		driver = MockDriver([self.company], records=[{"name": r} for r in refs])
		driver.clients[self.company] = client

		manager = AEATOutboxManager(clock=FakeClock())
		manager.drain([driver])

		# un lote con los registros en ORDEN
		self.assertEqual(len(driver.payloads), 1)
		company, sent = driver.payloads[0]
		self.assertEqual(company, self.company)
		self.assertEqual(sent, refs)
		# send llamado una vez con el payload del driver
		self.assertEqual(client.calls, 1)
		# response persistida con líneas por external_ref y entregada al driver
		self.assertEqual(len(driver.processed), 1)
		response, doc = driver.processed[0]
		self.assertEqual(response["CSV"], "A-TESTCSV")
		self._assert_response_persisted(doc, self.company, refs)

	def test_rate_limit_respected(self):
		"""timeout_seconds del driver: no se reenvía a la empresa hasta que
		pase (reloj inyectado — sin sleeps reales)."""
		client = FakeClient(responses=[ok_response(["BR-001"]) for _ in range(5)])
		driver = MockDriver([self.company], records=[{"name": "BR-001"}])
		driver.clients[self.company] = client
		driver.rate_limit = 60

		reloj = FakeClock()
		manager = AEATOutboxManager(clock=reloj)

		manager.drain([driver])
		self.assertEqual(client.calls, 1)

		# inmediatamente y a los 59s: bloqueado
		manager.drain([driver])
		reloj.sleep(59)
		manager.drain([driver])
		self.assertEqual(client.calls, 1)

		# a los 61s: permitido
		reloj.sleep(2)
		manager.drain([driver])
		self.assertEqual(client.calls, 2)

	def test_aeat_wait_merged_into_rate_limit(self):
		"""TiempoEsperaEnvio de la AEAT (>60s — spec 04 §8) manda sobre el
		rate-limit corto del driver."""
		client = FakeClient(responses=[ok_response(["BR-001"], wait_seconds=90) for _ in range(5)])
		driver = MockDriver([self.company], records=[{"name": "BR-001"}])
		driver.clients[self.company] = client
		driver.rate_limit = 10

		reloj = FakeClock()
		manager = AEATOutboxManager(clock=reloj)

		manager.drain([driver])
		self.assertEqual(client.calls, 1)

		# a los 50s: ni el rate-limit corto habilita — la AEAT pidió 90s
		reloj.sleep(50)
		manager.drain([driver])
		self.assertEqual(client.calls, 1)

		# a los 91s: permitido
		reloj.sleep(41)
		manager.drain([driver])
		self.assertEqual(client.calls, 2)

	def test_batch_limit_and_order(self):
		"""El lote se recorta a batch_limit (tope AEAT) preservando el orden
		del driver."""
		refs = [f"BR-{n:03}" for n in range(1, 6)]
		client = FakeClient(responses=[ok_response(refs[:3])])
		driver = MockDriver([self.company], records=[{"name": r} for r in refs])
		driver.clients[self.company] = client
		driver.batch = 3

		AEATOutboxManager(clock=FakeClock()).drain([driver])

		sent = driver.payloads[0][1]
		self.assertEqual(sent, refs[:3])

	def test_isolation_per_company(self):
		"""Un error en una empresa (falta de credencial → excepción en
		get_client) NO aborta el run: se registra con log_error y la siguiente
		empresa drena normal (spec 13 §5 — NUNCA throw en el bucle)."""
		client = FakeClient(responses=[ok_response(["BR-001"])])
		driver = MockDriver([GHOST_COMPANY, self.company], records=[{"name": "BR-001"}])
		driver.clients[self.company] = client
		driver.clients[GHOST_COMPANY] = FakeClient(error=RuntimeError("sin credencial"))

		manager = AEATOutboxManager(clock=FakeClock())
		manager.drain([driver])  # no debe propagar nada

		# la real drenó; la fantasma quedó aislada con Error Log
		self.assertEqual(client.calls, 1)
		self.assertEqual(len(driver.processed), 1)
		self.assertFalse(frappe.db.exists("ES AEAT Response", {"company": GHOST_COMPANY}))

		error_logs = frappe.get_all(
			"Error Log", filters={"method": f"AEAT VeriFactu: error drenando {GHOST_COMPANY}"}, pluck="name"
		)
		self.assertTrue(error_logs, "se esperaba frappe.log_error para la empresa fallida")

	def test_retries_backoff_and_limit_with_notification(self):
		"""Backoff exponencial (2s, 4s) entre intentos; al agotar el tope:
		estado visible (on_batch_failure), notificación y log — sin response."""
		client = FakeClient(error=ConnectionError("AEAT inaccesible"))
		driver = MockDriver([self.company], records=[{"name": "BR-001"}])
		driver.clients[self.company] = client
		driver.attempt_limit = 3

		reloj = FakeClock()
		manager = AEATOutboxManager(clock=reloj)
		# Los tests de la clase comparten transacción: los anteriores ya
		# persistieron respuestas de esta empresa — lo que este drain agotado
		# no debe hacer es añadir la suya.
		responses_before = frappe.db.count("ES AEAT Response", {"company": self.company})
		manager.drain([driver])

		self.assertEqual(client.calls, 3)
		self.assertEqual(reloj.sleeps, [2.0, 4.0])
		self.assertEqual(len(driver.batch_failures), 1)
		company, records, error = driver.batch_failures[0]
		self.assertEqual(company, self.company)
		self.assertEqual(records, [{"name": "BR-001"}])
		self.assertIsInstance(error, ConnectionError)

		# notificación de agotamiento por el canal in-app
		notifications = frappe.get_all(
			"Notification Log",
			filters={"for_user": "Administrator", "document_type": "Company", "document_name": self.company},
			pluck="subject",
		)
		self.assertTrue(any("reintentos de envío agotados" in a for a in notifications), notifications)
		# log del agotamiento
		self.assertTrue(
			frappe.get_all(
				"Error Log",
				filters={"method": f"AEAT VeriFactu: reintentos agotados para {self.company}"},
				pluck="name",
			)
		)
		# sin response persistida por ESTE drain (no la hubo)
		self.assertEqual(frappe.db.count("ES AEAT Response", {"company": self.company}), responses_before)

	def test_transient_retry_recovers(self):
		"""Un fallo transitorio seguido de éxito: reintenta con backoff y
		persiste la respuesta — el fault de conexión no pierde el lote."""
		client = FakeClient(responses=[ok_response(["BR-001"])])
		attempts = {"n": 0}
		original = client.send

		def send_unstable(payload):
			attempts["n"] += 1
			if attempts["n"] == 1:
				raise ConnectionError("timeout transitorio")
			return original(payload)

		client.send = send_unstable
		driver = MockDriver([self.company], records=[{"name": "BR-001"}])
		driver.clients[self.company] = client

		reloj = FakeClock()
		manager = AEATOutboxManager(clock=reloj)
		manager.drain([driver])

		self.assertEqual(attempts["n"], 2)
		self.assertEqual(reloj.sleeps, [2.0])
		self.assertEqual(len(driver.processed), 1)
		self.assertTrue(frappe.db.exists("ES AEAT Response", {"company": self.company}))

	def test_dispatcher_without_drivers_noop(self):
		"""Camino de producción hoy: sin drivers registrados, drain() es un
		no-op gracioso (el driver de VeriFactu llega en su lote)."""
		self.assertEqual(get_drivers("VeriFactu"), [])
		AEATOutboxManager(clock=FakeClock()).drain()  # no crash

	def test_dispatcher_registers_and_drains_per_service(self):
		driver = MockDriver([self.company])
		driver.clients[self.company] = FakeClient(responses=[ok_response(["BR-001", "BR-002"])])
		register_driver(driver)
		self.addCleanup(
			lambda: get_drivers.__globals__["_DRIVERS"].setdefault("VeriFactu", []).remove(driver)
		)

		self.assertIn(driver, get_drivers("VeriFactu"))
		AEATOutboxManager(clock=FakeClock()).drain()  # drena los registrados
		self.assertEqual(len(driver.processed), 1)
