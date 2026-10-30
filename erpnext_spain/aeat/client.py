# Cliente SOAP de la AEAT (spec 13 §4): factoría zeep con TLS mutua.
#
# CERO lógica de negocio: recibe un payload estructurado
# {"operacion": <método SOAP>, "datos": {kwargs del servicio}} y devuelve un
# dict serializable (tras helpers.serialize_object). Un SOAP Fault es una
# respuesta VÁLIDA de la AEAT (la conexión funcionó y el servidor rechazó la
# petición): se convierte a RespuestaLinea sintéticas por registro (patrón de
# la referencia) para que los procesadores trabajen un único formato. Los
# errores de transporte/conexión SÍ propagan: el manager los reintenta con
# backoff.
#
# Testable: `client_factory` inyectable sustituye la construcción de zeep
# (mock en aeat/tests/mock_aeat_client.py); el WSDL de VeriFactu se lee EN
# VIVO de ES Settings (editable, y producción vacío a propósito).

from __future__ import annotations

import re
from typing import Any

import frappe

ENV_TEST = "pruebas"
ENV_PRODUCTION = "produccion"
ENVIRONMENTS = (ENV_TEST, ENV_PRODUCTION)

# Registro declarativo por servicio (spec 13 §4). SII añade sus entradas en
# su fase (spec 05). VeriFactu: WSDL único con puertos pruebas/producción.
SERVICES: dict[str, dict[str, Any]] = {
	"VeriFactu": {
		# Campos de ES Settings de los que se lee el WSDL EN VIVO:
		"wsdl_settings": {ENV_TEST: "verifactu_wsdl_test", ENV_PRODUCTION: "verifactu_wsdl_production"},
		"service_name": "sfVerifactu",
	 "ports": {ENV_TEST: "SistemaVerifactuPruebas", ENV_PRODUCTION: "SistemaVerifactu"},
	},
}

# Fallback del entorno de pruebas si ES Settings estuviera vacío (Batch 1 lo
# deja con este mismo valor por defecto; producción NUNCA tiene fallback).
WSDL_TEST_DEFAULT = (
	"https://prewww2.aeat.es/static_files/common/internet/dep/aplicaciones/es/"
	"aeat/tikeV1.0/cont/ws/SistemaFacturacion.wsdl"
)


def _wsdl_from_settings(service: str, environment: str) -> str:
	"""WSDL del servicio+entorno, leído EN VIVO de ES Settings.

	Producción vacío es un BLOQUEO deliberado (diseño de Batch 1): no hay
	fallback — jamás se enviaría a producción contra un endpoint de pruebas.
	"""
	cfg = SERVICES[service]
	field = cfg["wsdl_settings"][environment]
	wsdl = (frappe.get_cached_doc("ES Settings").get(field) or "").strip()
	if wsdl:
		return wsdl
	if environment == ENV_TEST:
		return WSDL_TEST_DEFAULT
	frappe.throw(
		f"No hay WSDL de producción configurado para {service} en ES Settings"
		" (campo «WSDL VeriFactu (producción)»). Remedio: indique el endpoint de"
		" producción que le facilite su proveedor/certificado antes de remitir a"
		" la AEAT en producción — no se aplica ningún valor por defecto para no"
		" arriesgar envíos reales contra un endpoint incorrecto.",
		frappe.ValidationError,
	)


def _enabled_credential_pem_paths(company: str, service: str) -> tuple[str, str]:
	"""Rutas de los PEM de la credencial HABILITADA de (empresa, propósito= servicio)."""
	from erpnext_spain.aeat.doctype.es_aeat_credential.es_aeat_credential import pem_paths

	if not frappe.db.exists("ES AEAT Credential", {"company": company, "purpose": service, "enabled": 1}):
		frappe.throw(
			f"No hay credencial AEAT habilitada para {company} ({service})."
			" Remedio: suba el certificado p12 en «ES AEAT Credential» y active la"
			" credencial antes de comunicar con la AEAT.",
			frappe.ValidationError,
		)
	return pem_paths(company, service)


class AEATClient:
	"""Cliente SOAP de un servicio AEAT para una empresa y entorno.

	TLS mutua con los PEM de la credencial de la empresa (private/files);
	timeouts configurables; `client_factory` inyectable para tests.
	"""

	def __init__(
		self,
		*,
		service: str,
		environment: str,
		company: str,
		timeout: float = 15.0,
		client_factory: Any = None,
	):
		if service not in SERVICES:
			frappe.throw(
				f"Servicio AEAT desconocido: {service}."
				f" Remedio: use uno de {', '.join(SERVICES)} o registre el servicio en"
				" erpnext_spain.aeat.client.SERVICES.",
				frappe.ValidationError,
			)
		if environment not in ENVIRONMENTS:
			frappe.throw(
				f"Entorno AEAT desconocido: {environment}. Remedio: use"
				f" {' o '.join(ENVIRONMENTS)}.",
				frappe.ValidationError,
			)

		self.service = service
		self.environment = environment
		self.company = company
		self.timeout = timeout

		cfg = SERVICES[service]
		self.wsdl_url = _wsdl_from_settings(service, environment)
		self.cert_pem, self.key_pem = _enabled_credential_pem_paths(company, service)

		factory = client_factory or _build_zeep_client
		self.client = factory(
			wsdl=self.wsdl_url,
			cert_pem=self.cert_pem,
			key_pem=self.key_pem,
			timeout=timeout,
			service_name=cfg["service_name"],
			port_name=cfg["ports"][environment],
		)

	def send(self, payload: dict) -> dict:
		"""Envía un payload estructurado y devuelve la respuesta serializable.

		SOAP Fault → RespuestaLinea sintéticas (patrón de la referencia) para
		que los procesadores trabajen un único formato. Errores de conexión
		propagan (el manager reintenta); cero lógica de negocio aquí.
		"""
		from zeep.exceptions import Fault
		from zeep import helpers

		operation = payload.get("operacion")
		data = payload.get("datos")
		if not operation or not isinstance(data, dict):
			frappe.throw(
				"Payload AEAT mal formado: se espera {'operacion': <método SOAP>,"
				" 'datos': {argumentos del servicio}}.",
				frappe.ValidationError,
			)

		try:
			response = getattr(self.client.service, operation)(**data)
		except Fault as fault:
			return _fault_to_synthetic_response(self.service, fault, data)

		return dict(helpers.serialize_object(response, dict))


def _build_zeep_client(
	*, wsdl: str, cert_pem: str, key_pem: str, timeout: float, service_name: str, port_name: str
):
	"""Cliente zeep con sesión requests y TLS mutua (cert de la empresa)."""
	import requests
	from zeep import Client, Settings
	from zeep.transports import Transport

	session = requests.Session()
	session.cert = (cert_pem, key_pem)
	session.verify = True

	settings = Settings(
		strict=True,
		raw_response=False,
		force_https=True,
		xml_huge_tree=False,
		forbid_dtd=False,
		forbid_entities=False,
		forbid_external=True,
		xsd_ignore_sequence_order=False,
	)

	return Client(
		wsdl=wsdl,
		settings=settings,
		transport=Transport(session=session, timeout=timeout),
		service_name=service_name,
		port_name=port_name,
	)


def _fault_to_synthetic_response(service: str, fault: Any, data: dict) -> dict:
	"""SOAP Fault → respuesta sintética con la misma forma que la AEAT devuelve
	en éxito (patrón de la referencia): una RespuestaLinea Incorrecto por cada
	registro remitido, con el código del Fault (patrón `Codigo[N]` del mensaje
	AEAT, o el código del Fault como fallback).
	"""
	message = str(fault)
	match = re.search(r"Codigo\[(\d+)\]", message)
	error_code = match.group(1) if match else str(getattr(fault, "code", "") or "")

	lines: list[dict] = []
	for record in data.get("RegistroFactura") or []:
		if not isinstance(record, dict):
			continue
		issuance = record.get("RegistroAlta")
		cancellation = record.get("RegistroAnulacion")
		if issuance:
			idf = issuance.get("IDFactura") or {}
			invoice_id = {
				"IDEmisorFactura": idf.get("IDEmisorFactura"),
				"NumSerieFactura": idf.get("NumSerieFactura"),
				"FechaExpedicionFactura": idf.get("FechaExpedicionFactura"),
			}
			external_ref = issuance.get("RefExterna")
			operation_type = "Alta"
		elif cancellation:
			idf = cancellation.get("IDFactura") or {}
			invoice_id = {
				"IDEmisorFactura": idf.get("IDEmisorFacturaAnulada"),
				"NumSerieFactura": idf.get("NumSerieFacturaAnulada"),
				"FechaExpedicionFactura": idf.get("FechaExpedicionFacturaAnulada"),
			}
			external_ref = cancellation.get("RefExterna")
			operation_type = "Anulacion"
		else:
			continue
		lines.append(
			{
				"IDFactura": invoice_id,
				"Operacion": {
					"TipoOperacion": operation_type,
					"Subsanacion": None,
					"RechazoPrevio": None,
					"SinRegistroPrevio": None,
				},
				"RefExterna": external_ref,
				"EstadoRegistro": "Incorrecto",
				"CodigoErrorRegistro": error_code,
				"DescripcionErrorRegistro": message,
				"RegistroDuplicado": None,
			}
		)

	return {
		"fault": True,
		"fault_code": str(getattr(fault, "code", "") or ""),
		"fault_message": message,
		"EstadoEnvio": "Incorrecto",
		"RespuestaLinea": lines,
	}
