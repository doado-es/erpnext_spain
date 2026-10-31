# Tests del mock grabar/reproducir del cliente AEAT (spec 13, tarea 5),
# sembrado con los ejemplos reales de la referencia (tests/data).

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.aeat.tests import mock_aeat_client as mock_mod
from erpnext_spain.aeat.tests.mock_aeat_client import (
	MockAEATClient,
	load_seed,
	mock_client_factory,
)

PAYLOAD = {"operacion": "RegFactuSistemaFacturacion", "datos": {"Cabecera": {}, "RegistroFactura": []}}
PAYLOAD_CONSULTA = {"operacion": "ConsultaFactuSistemaFacturacion", "datos": {"FiltroConsulta": {}}}


class TestMockAEATClient(IntegrationTestCase):
	def test_seeds_load_from_tests_data(self):
		seed = load_seed("alta_aceptada_con_errores")
		self.assertEqual(seed["EstadoEnvio"], "ParcialmenteCorrecto")
		self.assertEqual(seed["RespuestaLinea"][0]["EstadoRegistro"], "AceptadoConErrores")
		self.assertEqual(seed["RespuestaLinea"][0]["CodigoErrorRegistro"], 2004)

		duplicado = load_seed("registro_duplicado_incorrecto")
		self.assertEqual(duplicado["EstadoEnvio"], "Incorrecto")
		self.assertIsNotNone(duplicado["RespuestaLinea"][0]["RegistroDuplicado"])

	def test_replay_falls_back_to_default_seed(self):
		mock = MockAEATClient()
		response = mock.send(PAYLOAD)
		self.assertEqual(response["EstadoEnvio"], "ParcialmenteCorrecto")
		self.assertEqual(mock.sent_payloads, [PAYLOAD])

	def test_replay_response_by_operation(self):
		respuesta_duplicado = load_seed("registro_duplicado_incorrecto")
		mock = MockAEATClient(responses={"ConsultaFactuSistemaFacturacion": respuesta_duplicado})
		self.assertEqual(mock.send(PAYLOAD_CONSULTA)["EstadoEnvio"], "Incorrecto")
		# otra operación → semilla por defecto
		self.assertEqual(mock.send(PAYLOAD)["EstadoEnvio"], "ParcialmenteCorrecto")

	def test_replay_fifo_queue_per_operation(self):
		mock = MockAEATClient(
			responses={
				"RegFactuSistemaFacturacion": [
					load_seed("alta_aceptada_con_errores"),
					load_seed("registro_duplicado_incorrecto"),
				]
			}
		)
		self.assertEqual(mock.send(PAYLOAD)["EstadoEnvio"], "ParcialmenteCorrecto")
		self.assertEqual(mock.send(PAYLOAD)["EstadoEnvio"], "Incorrecto")

	def test_record_records_and_replays(self):
		import shutil

		directory = Path(tempfile.mkdtemp(prefix="es_mock_record_"))
		self.addCleanup(shutil.rmtree, directory, ignore_errors=True)

		# grabar: envuelve un "cliente real" (aquí, otro mock con respuestas)
		response = load_seed("registro_duplicado_incorrecto")
		real = MockAEATClient(responses={"RegFactuSistemaFacturacion": response})
		recorder = MockAEATClient(mode="record", real_client=real, recordings_dir=directory)

		self.assertEqual(recorder.send(PAYLOAD)["EstadoEnvio"], "Incorrecto")
		files = sorted(directory.glob("*.json"))
		self.assertEqual(len(files), 1)
		# frappe.scrub no separa CamelCase: RegFactuSistemaFacturacion → regfactusistemafacturacion
		self.assertTrue(files[0].name.startswith("regfactusistemafacturacion-"))

		recorded = json.loads(files[0].read_text(encoding="utf-8"))
		self.assertEqual(recorded["payload"]["operacion"], PAYLOAD["operacion"])
		self.assertEqual(recorded["respuesta"]["EstadoEnvio"], "Incorrecto")

		# reproducir desde la grabación, sin real_client
		replayer = MockAEATClient(
			mode="replay", recordings_dir=directory, default_seed="alta_aceptada_con_errores"
		)
		self.assertEqual(replayer.send(PAYLOAD)["EstadoEnvio"], "Incorrecto")

	def test_record_without_real_client_blocks(self):
		with self.assertRaises(frappe.ValidationError):
			MockAEATClient(mode="record")

	def test_build_client_real_without_site_flag(self):
		"""Sin flag es_aeat_mock en la config del site, build_client va por el
		cliente REAL: con una empresa sin credencial habilitada bloquea con
		remedio (el mock jamás lanza ese error)."""
		from frappe.config import get_common_site_config

		if frappe.conf.get(mock_mod.ES_AEAT_MOCK_CONF) or get_common_site_config().get(
			mock_mod.ES_AEAT_MOCK_CONF
		):
			self.skipTest("el site tiene el flag es_aeat_mock activo")

		with self.assertRaises(frappe.ValidationError) as ctx:
			mock_mod.build_client("VeriFactu", "pruebas", "ES Empresa Inexistente AEAT")
		self.assertIn("credencial AEAT habilitada", str(ctx.exception))
