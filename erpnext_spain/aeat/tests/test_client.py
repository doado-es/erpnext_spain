# Tests del client SOAP AEAT (spec 13 §4): factoría con WSDL vivo de ES
# Settings, TLS mutua, puertos por entorno, error bloqueante de producción
# vacío y conversión de SOAP Fault → líneas sintéticas. Cliente zeep mockeado
# via client_factory (aeat/tests/mock_aeat_client).

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from zeep.exceptions import Fault

from erpnext_spain.aeat.client import ENV_PRODUCTION, ENV_TEST, SERVICES, AEATClient
from erpnext_spain.aeat.tests.helpers import (
	clean_pem,
	generate_p12,
	test_company,
	write_private_p12,
)
from erpnext_spain.aeat.tests.mock_aeat_client import (
	load_seed,
	mock_client_factory,
)

SUBMISSION = {
	"operacion": "RegFactuSistemaFacturacion",
	"datos": {
		"Cabecera": {"ObligadoEmision": {"NombreRazon": "Empresa Ejemplo S.L.", "NIF": "12345678Z"}},
		"RegistroFactura": [
			{
				"RegistroAlta": {
					"IDFactura": {
						"IDEmisorFactura": "12345678Z",
						"NumSerieFactura": "FACT-2026-001",
						"FechaExpedicionFactura": "30-01-2026",
					},
					"RefExterna": "BR-001",
				}
			},
			{
				"RegistroAnulacion": {
					"IDFactura": {
						"IDEmisorFacturaAnulada": "12345678Z",
						"NumSerieFacturaAnulada": "FACT-2026-000",
						"FechaExpedicionFacturaAnulada": "29-01-2026",
					},
					"RefExterna": "BR-000",
				}
			},
		],
	},
}


class TestAEATClient(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.url_p12 = write_private_p12("es_test_client.p12", generate_p12()[0])
		frappe.get_doc(
			{
				"doctype": "ES AEAT Credential",
				"company": cls.company,
				"purpose": "VeriFactu",
				"cert_file": cls.url_p12,
				"cert_password": "es-test-pass",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		cls.addClassCleanup(clean_pem, cls.company, "VeriFactu")

	def _production_wsdl(self, value: str | None):
		"""Fija (y restaura al terminar el test) el WSDL de producción."""
		settings = frappe.get_doc("ES Settings")
		previous = settings.verifactu_wsdl_production
		settings.verifactu_wsdl_production = value or ""
		settings.save(ignore_permissions=True)

		def restore():
			s = frappe.get_doc("ES Settings")
			s.verifactu_wsdl_production = previous
			s.save(ignore_permissions=True)

		self.addCleanup(restore)

	def test_verifactu_service_registry(self):
		self.assertIn("VeriFactu", SERVICES)
		cfg = SERVICES["VeriFactu"]
		self.assertEqual(cfg["ports"][ENV_TEST], "SistemaVerifactuPruebas")
		self.assertEqual(cfg["ports"][ENV_PRODUCTION], "SistemaVerifactu")

	def test_live_wsdl_from_settings_and_ports_per_environment(self):
		self._production_wsdl("https://v16.example.com/Verifactu.wsdl")

		for environment, expected_port in (
			(ENV_TEST, "SistemaVerifactuPruebas"),
			(ENV_PRODUCTION, "SistemaVerifactu"),
		):
			captured: dict[str, object] = {}

			def factory(**kwargs):
				captured.update(kwargs)
				return frappe._dict(service=frappe._dict())

			AEATClient(
				service="VeriFactu",
				environment=environment,
				company=self.company,
				client_factory=factory,
			)
			self.assertEqual(captured["port_name"], expected_port)
			self.assertEqual(captured["service_name"], "sfVerifactu")
			if environment == ENV_PRODUCTION:
				self.assertEqual(captured["wsdl"], "https://v16.example.com/Verifactu.wsdl")
			else:
				self.assertIn("SistemaFacturacion.wsdl", captured["wsdl"])

	def test_empty_production_wsdl_blocks_with_remedy(self):
		"""Producción vacío es un BLOQUEO: jamás cae al WSDL de pruebas."""
		self._production_wsdl(None)

		with self.assertRaises(frappe.ValidationError) as ctx:
			AEATClient(
				service="VeriFactu",
				environment=ENV_PRODUCTION,
				company=self.company,
				client_factory=mock_client_factory({}),
			)
		mensaje = str(ctx.exception)
		self.assertIn("WSDL de producción", mensaje)
		self.assertIn("Remedio", mensaje)
		# NUNCA fallback al endpoint de pruebas
		self.assertNotIn("prewww2", mensaje)

	def test_unknown_service_or_environment_blocks(self):
		for kwargs in (
			{"service": "NoExiste", "environment": ENV_TEST},
			{"service": "VeriFactu", "environment": "staging"},
		):
			with self.assertRaises(frappe.ValidationError):
				AEATClient(company=self.company, client_factory=mock_client_factory({}), **kwargs)

	def test_mutual_tls_with_credential_pem(self):
		import os

		captured: dict[str, object] = {}

		def factory(**kwargs):
			captured.update(kwargs)
			return frappe._dict(service=frappe._dict())

		AEATClient(service="VeriFactu", environment=ENV_TEST, company=self.company, client_factory=factory)
		self.assertTrue(os.path.exists(captured["cert_pem"]))
		self.assertTrue(os.path.exists(captured["key_pem"]))
		self.assertIn("private", captured["cert_pem"])
		self.assertIn("private", captured["key_pem"])

	def test_disabled_credential_blocks_with_remedy(self):
		credential = frappe.get_doc("ES AEAT Credential", {"company": self.company})
		credential.enabled = 0
		credential.save(ignore_permissions=True)

		def restore():
			credential.enabled = 1
			credential.save(ignore_permissions=True)

		self.addCleanup(restore)

		with self.assertRaises(frappe.ValidationError) as ctx:
			AEATClient(
				service="VeriFactu",
				environment=ENV_TEST,
				company=self.company,
				client_factory=mock_client_factory({}),
			)
		self.assertIn("credencial AEAT habilitada", str(ctx.exception))

	def test_send_returns_serializable_dict(self):
		seed = load_seed("alta_aceptada_con_errores")
		client = AEATClient(
			service="VeriFactu",
			environment=ENV_TEST,
			company=self.company,
			client_factory=mock_client_factory({"RegFactuSistemaFacturacion": seed}),
		)
		response = client.send(SUBMISSION)
		self.assertEqual(response["EstadoEnvio"], "ParcialmenteCorrecto")
		self.assertEqual(response["CSV"], "A-EXAMPLECSV00001")
		self.assertEqual(response["TiempoEsperaEnvio"], "60")
		# serializable (persistencia en JSON del manager)
		frappe.as_json(response)

	def test_send_malformed_payload_blocks(self):
		client = AEATClient(
			service="VeriFactu",
			environment=ENV_TEST,
			company=self.company,
			client_factory=mock_client_factory({}),
		)
		with self.assertRaises(frappe.ValidationError):
			client.send({"datos": {}})

	def test_soap_fault_converted_to_synthetic_lines(self):
		"""SOAP Fault = respuesta VÁLIDA de la AEAT: una RespuestaLinea
		Incorrecto por registro remitido (patrón de la referencia)."""
		fault = Fault("Codigo[2004] El valor del campo FechaHoraHusoGenRegistro no es correcto.", code=1000)
		client = AEATClient(
			service="VeriFactu",
			environment=ENV_TEST,
			company=self.company,
			client_factory=mock_client_factory({"RegFactuSistemaFacturacion": fault}),
		)
		response = client.send(SUBMISSION)

		self.assertTrue(response["fault"])
		self.assertEqual(response["EstadoEnvio"], "Incorrecto")
		self.assertEqual(response["fault_code"], "1000")
		self.assertIn("fault_message", response)

		lines = response["RespuestaLinea"]
		self.assertEqual(len(lines), 2)

		issuance, cancellation = lines
		self.assertEqual(issuance["EstadoRegistro"], "Incorrecto")
		self.assertEqual(issuance["CodigoErrorRegistro"], "2004")  # código del patrón Codigo[N]
		self.assertEqual(issuance["RefExterna"], "BR-001")
		self.assertEqual(issuance["Operacion"]["TipoOperacion"], "Alta")
		self.assertEqual(issuance["IDFactura"]["NumSerieFactura"], "FACT-2026-001")

		self.assertEqual(cancellation["RefExterna"], "BR-000")
		self.assertEqual(cancellation["Operacion"]["TipoOperacion"], "Anulacion")
		self.assertEqual(cancellation["IDFactura"]["NumSerieFactura"], "FACT-2026-000")

	def test_soap_fault_without_code_uses_fault_code(self):
		fault = Fault("Error interno de la AEAT.", code="SISTEMA")
		client = AEATClient(
			service="VeriFactu",
			environment=ENV_TEST,
			company=self.company,
			client_factory=mock_client_factory({"RegFactuSistemaFacturacion": fault}),
		)
		response = client.send(SUBMISSION)
		self.assertEqual(response["RespuestaLinea"][0]["CodigoErrorRegistro"], "SISTEMA")

	def test_connection_error_propagates_for_manager_retry(self):
		"""Los errores de transporte NO son respuesta AEAT: propagan (el manager
		los reintenta con backoff)."""
		client = AEATClient(
			service="VeriFactu",
			environment=ENV_TEST,
			company=self.company,
			client_factory=mock_client_factory({"RegFactuSistemaFacturacion": ConnectionError("timeout")}),
		)
		with self.assertRaises(ConnectionError):
			client.send(SUBMISSION)
