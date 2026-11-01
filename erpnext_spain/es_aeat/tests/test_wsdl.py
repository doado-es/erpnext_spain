# Tests de la resolución local del WSDL y los esquemas de la AEAT (spec 01 §8,
# H7): el cliente se construye sin red con zeep >= 4.3.3 y forbid_external.

from __future__ import annotations

import re
import socket
import tempfile
import unittest.mock
from pathlib import Path

import frappe
import requests
from frappe.tests import UnitTestCase

from erpnext_spain.es_aeat.client import _build_zeep_client, load_wsdl_client, zeep_settings
from erpnext_spain.es_aeat.wsdl import OFFICIAL_WSDLS, local_wsdl, rewrite_schema_locations
from erpnext_spain.schemas import REMOTE_SCHEMAS, SCHEMA_ROOT, VERIFACTU_WSDL, XMLDSIG_SCHEMA

TEST_URL = (
	"https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/"
	"aeat/tikeV1.0/cont/ws/SistemaFacturacion.wsdl"
)
PRODUCTION_URL = (
	"https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/"
	"aeat/tikeV1.0/cont/ws/SistemaFacturacion.wsdl"
)
XMLDSIG_URL = "http://www.w3.org/TR/xmldsig-core/xmldsig-core-schema.xsd"


def _no_network(*args, **kwargs):
	raise AssertionError("El test ha intentado acceder a la red")


class OfflineMixin:
	"""Cualquier conexión de red (socket o requests) hace fallar el test."""

	def setUp(self):
		super().setUp()
		for target in ("socket.socket.connect", "requests.Session.send"):
			patcher = unittest.mock.patch(target, _no_network)
			patcher.start()
			self.addCleanup(patcher.stop)


class TestLocalWsdl(OfflineMixin, UnitTestCase):
	def test_forbid_external_stays_enabled(self):
		self.assertTrue(zeep_settings().forbid_external)

	def test_official_urls_map_to_bundled_copy(self):
		self.assertEqual(local_wsdl(TEST_URL), str(VERIFACTU_WSDL))
		self.assertEqual(local_wsdl(PRODUCTION_URL), str(VERIFACTU_WSDL))
		self.assertEqual(local_wsdl("https://example.com/otro.wsdl"), "https://example.com/otro.wsdl")
		self.assertEqual(set(OFFICIAL_WSDLS), {TEST_URL, PRODUCTION_URL})

	def test_rewrite_only_known_remote_schemas(self):
		content = (
			b'<schema><import namespace="a" schemaLocation="' + XMLDSIG_URL.encode() + b'"/>'
			b"<import namespace='b' schemaLocation='Local.xsd'/></schema>"
		)
		rewritten = rewrite_schema_locations(content, REMOTE_SCHEMAS)
		self.assertIn(f'schemaLocation="{XMLDSIG_SCHEMA}"'.encode(), rewritten)
		self.assertIn(b"schemaLocation='Local.xsd'", rewritten)
		self.assertNotIn(XMLDSIG_URL.encode(), rewritten)

	def test_bundled_schemas_have_no_unresolved_remote_imports(self):
		"""Todo `schemaLocation` de las copias es relativo o tiene copia local."""
		pattern = re.compile(r"""schemaLocation\s*=\s*["']([^"']+)["']""")
		files = [*SCHEMA_ROOT.rglob("*.xsd"), *SCHEMA_ROOT.rglob("*.wsdl")]
		self.assertTrue(files)
		for path in files:
			for location in pattern.findall(path.read_text(encoding="utf-8")):
				if location.startswith(("http://", "https://")):
					self.assertIn(location, REMOTE_SCHEMAS, f"{path.name}: {location}")
					self.assertTrue(REMOTE_SCHEMAS[location].is_file())
				else:
					self.assertTrue((path.parent / location).is_file(), f"{path.name}: {location}")

	def test_client_builds_offline_from_official_urls(self):
		"""Construcción real del cliente (sesión TLS incluida), sin red."""
		for url, port, address in (
			(TEST_URL, "SistemaVerifactuPruebas", "https://prewww1.aeat.es/"),
			(PRODUCTION_URL, "SistemaVerifactu", "https://www1.agenciatributaria.gob.es/"),
		):
			client = _build_zeep_client(
				wsdl=url,
				cert_pem="/nonexistent/cert.pem",
				key_pem="/nonexistent/key.pem",
				timeout=5,
				service_name="sfVerifactu",
				port_name=port,
			)
			self.assertTrue(client.service._binding_options["address"].startswith(address))
			self.assertEqual(client.transport.operation_timeout, 5)
			# El esquema de firma se ha cargado desde la copia local.
			self.assertTrue(client.wsdl.types.get_type("{http://www.w3.org/2000/09/xmldsig#}SignatureType"))

	def test_unknown_remote_import_blocked_with_remedy(self):
		with tempfile.TemporaryDirectory() as directory:
			wsdl = Path(directory) / "Remoto.wsdl"
			wsdl.write_text(
				VERIFACTU_WSDL.read_text(encoding="utf-8").replace(
					'schemaLocation="SuministroInformacion.xsd"',
					'schemaLocation="https://example.invalid/SuministroInformacion.xsd"',
				),
				encoding="utf-8",
			)
			with self.assertRaises(frappe.ValidationError) as ctx:
				load_wsdl_client(str(wsdl))
		self.assertIn("example.invalid", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))
