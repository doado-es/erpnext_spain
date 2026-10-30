# Consulta de registros de facturación a la AEAT — lote 6b (spec 04 §10).
#
# «ES Verifactu Aeat Query»: la operación ConsultaFactuSistemaFacturacion del
# servicio VeriFactu (WSDL, puerto sfVerifactu): dados unos filtros
# (contraparte, nº de factura, rango de fechas de expedición) devuelve los
# registros ALMACENADOS por la AEAT con su estado consolidado (Correcto /
# AceptadoConErrores / Anulado) — la vista de la AEAT del libro del SIF.
#
# Defecto v1 que este doctype repara (el `consultar` de la referencia,
# verifactu/doctype/es_verifactu_aeat_query): la compañía se tomaba
# IMPLÍCITAMENTE (`frappe.db.get_list("Company").pop()` — ¡la primera del
# site!) y el AEATClient se construía SIN empresa. Aquí NADA es implícito:
# 1. `company` es un campo requerido del doctype.
# 2. `credential` es EXPLÍCITA (default documentado del campo
#    es_verifactu_credential de la Company) y se valida contra
#    (empresa, VeriFactu, habilitada) ANTES de tocar la red.
# 3. Los filtros son los del formulario: empresa + credencial + filtros,
#    nada del entorno se cuela en la petición.
#
# Forma wire (espejo del WSDL ConsultaLR.xsd — misma llamada que la
# referencia, aeat_lib/aeat_client.py consultar_facturas):
#   {"operacion": "ConsultaFactuSistemaFacturacion",
#    "datos": {"Cabecera": {"IDVersion": "1.0",          ← CabeceraConsultaSf
#                              "ObligadoEmision": {NombreRazon, NIF de la Company}},
#              "FiltroConsulta": {"PeriodoImputacion": {Ejercicio, Periodo},
#                                  "NumSerieFactura"?,   ← opcional: nº de factura
#                                  "Contraparte"?,       ← opcional: NIF del tercero
#                                  "FechaExpedicionFactura": {"RangoFechaExpedicion": {Desde?, Hasta?}}?}}}
#
# PeriodoImputacion es OBLIGATORIO en el WSDL (la consulta es POR PERÍODO
# impositivo): se deriva del inicio del rango de fechas (o del período
# corriente en huso de Madrid si no hay rango). El resto de filtros viaja
# solo si está cumplimentado (elementos opcionales de LRFiltroRegFacturacion).
#
# El cliente se construye con la factory conmutada por el flag del site
# `es_aeat_mock` (mismo patrón que el driver de remisión): producción = TLS
# mutua con los PEM de la credencial de la empresa; tests = mock inyectable
# (mock_client_factory de aeat/tests/mock_aeat_client.py).

from __future__ import annotations

from typing import Any

import frappe
from frappe.model.document import Document

from erpnext_spain.aeat.client import ENV_PRODUCTION, ENV_TEST
from erpnext_spain.aeat.tests.mock_aeat_client import build_client
from erpnext_spain.aeat.utils import format_aeat_date, has_aeat_permission, now_aeat

DOCTYPE = "ES Verifactu Aeat Query"

# Propósito de la credencial == llave del servicio en el dispatcher AEAT.
VERIFACTU_PURPOSE = "VeriFactu"

# Operación SOAP de consulta del WSDL VeriFactu (ConsultaFactuSistemaFacturacion).
QUERY_OPERATION = "ConsultaFactuSistemaFacturacion"

# Elemento de la respuesta con los registros devueltos (RespuestaConsultaLR.xsd).
RECORDS_KEY = "RegistroRespuestaConsultaFactuSistemaFacturacion"

# Modo operativo de la Company → entorno del cliente (mismo criterio que el
# driver de remisión, es_verifactu/driver.py get_client).
PRODUCTION_MODE = "Producción"

# CabeceraConsultaSf exige la versión del esquema (la remisión NO la lleva:
# su CabeceraType es solo ObligadoEmision).
ID_VERSION = "1.0"


class ESVerifactuAeatQuery(Document):
	def validate(self):
		self._default_credential()
		self._validate_date_range()

	def _default_credential(self) -> None:
		"""Credencial explícita con default documentado (spec 04 §10): si el
		campo viene vacío se toma el configurado en la ficha de la compañía
		(la UI además hace fetch_from del mismo campo). query_aeat valida
		el RESULTADO — nada queda al azar del entorno."""
		if self.credential or not self.company:
			return
		company_credential = frappe.db.get_value("Company", self.company, "es_verifactu_credential")
		if company_credential:
			self.credential = company_credential

	def _validate_date_range(self) -> None:
		"""El rango de expedición es inclusivo y coherente (Desde ≤ Hasta)."""
		if self.from_date and self.to_date and self.from_date > self.to_date:
			frappe.throw(
				f"El rango de fechas de expedición es inverso (desde {self.from_date}"
				f" hasta {self.to_date}). Remedio: fije «Expedida desde» anterior o"
				" igual a «Expedida hasta» — la AEAT rechazaría el filtro.",
				frappe.ValidationError,
			)


@frappe.whitelist()
def query_aeat(name: str) -> dict:
	"""Ejecuta la consulta a la AEAT del doc «ES Verifactu Aeat Query» y
	persiste la respuesta (crudo + una fila por registro devuelto).

	Guardas (con remedio, en orden):
	1. Permiso explícito (empresa, VeriFactu) — doc 12 §18: la consulta usa
	   la credencial de la empresa contra la AEAT, no basta el permiso del
	   doctype.
	2. Credencial EXPLÍCITA de la empresa (habilitada) — fix del defecto v1.
	3. Identidad fiscal de la compañía (Cabecera con NIF obligatorio).

	Re-consultar REEMPLAZA los resultados: la consulta es una foto puntual
	de la AEAT (el crudo queda en `result` para auditoría).

	:param name: docname del ES Verifactu Aeat Query.
	:return: la respuesta cruda serializable de la AEAT.
	"""
	doc = frappe.get_doc(DOCTYPE, name)

	if not has_aeat_permission(frappe.session.user, doc.company, VERIFACTU_PURPOSE):
		frappe.throw(
			f"El usuario {frappe.session.user} no tiene permiso AEAT de {doc.company}"
			f" para el propósito {VERIFACTU_PURPOSE}: la consulta usa la credencial de"
			" la empresa contra la AEAT y exige el chequeo explícito por"
			" empresa+propósito (doc 12 §18). Remedio: conceda al usuario un rol con"
			" permiso (roles de notificación de la compañía o, en su defecto,"
			" Accounts Manager) y acceso de lectura a la compañía.",
			frappe.PermissionError,
		)

	_validate_credential(doc)

	response = _client(doc.company).send(
		{
			"operacion": QUERY_OPERATION,
			"datos": {"Cabecera": _header(doc.company), "FiltroConsulta": _query_filters(doc)},
		}
	)

	_persist(doc, response)
	return response


def _validate_credential(doc: Document) -> None:
	"""Credencial EXPLÍCITA de la consulta (fix del v1, spec 04 §10): debe
	existir, ser de ESTA compañía, del propósito VeriFactu y estar
	habilitada. Sin credencial no hay TLS mutua y no hay consulta."""
	if not doc.credential:
		frappe.throw(
			f"La consulta de {doc.company} exige una credencial AEAT ({VERIFACTU_PURPOSE})"
			" explícita: es la identidad TLS mutua con la que se firma la petición."
			" Remedio: fije el campo «Credencial AEAT» — el formulario lo toma de"
			" la ficha de la compañía — y reintente.",
			frappe.ValidationError,
		)

	credential_data = frappe.db.get_value(
		"ES AEAT Credential",
		doc.credential,
		["company", "purpose", "enabled"],
		as_dict=True,
	)
	if (
		not credential_data
		or credential_data.company != doc.company
		or credential_data.purpose != VERIFACTU_PURPOSE
		or not credential_data.enabled
	):
		frappe.throw(
			f"La credencial {doc.credential} no es una credencial {VERIFACTU_PURPOSE}"
			f" habilitada de {doc.company}: la consulta usa la identidad TLS de la"
			" EMPRESA que consulta (defecto v1 corregido: la compañía y la"
			" credencial nunca se toman implícitamente del site). Remedio: fije"
			" la credencial habilitada de la compañía en la consulta, o habilite"
			" la credencial en «ES AEAT Credential» (propósito VeriFactu).",
			frappe.ValidationError,
		)


def _header(company: str) -> dict:
	"""CabeceraConsultaSf (WSDL): IDVersion + ObligadoEmision con la identidad
	fiscal de la Company. El NIF es obligatorio (NIFType, 9 caracteres)."""
	conf = frappe.db.get_value("Company", company, ["company_name", "tax_id"], as_dict=True)
	if not conf.tax_id:
		frappe.throw(
			f"La compañía {company} no tiene N.I.F.: la cabecera de la consulta"
			" (ObligadoEmision) lo exige y la AEAT rechazaría la petición."
			" Remedio: fije el «Tax ID» de la compañía en su ficha y reintente"
			" la consulta.",
			frappe.ValidationError,
		)
	return {
		"IDVersion": ID_VERSION,
		"ObligadoEmision": {"NombreRazon": conf.company_name, "NIF": conf.tax_id},
	}


def _query_filters(doc: Document) -> dict:
	"""LRFiltroRegFacturacionType (WSDL): PeriodoImputacion obligatorio (se
	deriva del inicio del rango, o del período corriente de Madrid sin
	rango) + los filtros opcionales SOLO si están cumplimentados, en el
	orden del esquema."""
	base = frappe.utils.getdate(doc.from_date) if doc.from_date else now_aeat().date()
	filters = {
		"PeriodoImputacion": {"Ejercicio": str(base.year), "Periodo": f"{base.month:02d}"}
	}

	if doc.series_number:
		filters["NumSerieFactura"] = doc.series_number

	if doc.counterparty_nif:
		# ContraparteConsultaType exige NombreRazon (TextMax120) además del
		# NIF: se repite el propio NIF — el doctype solo captura el
		# identificador y la AEAT casa contrapartes por NIF.
		filters["Contraparte"] = {"NombreRazon": doc.counterparty_nif, "NIF": doc.counterparty_nif}

	if doc.from_date or doc.to_date:
		rango: dict[str, str] = {}
		if doc.from_date:
			rango["Desde"] = format_aeat_date(doc.from_date)
		if doc.to_date:
			rango["Hasta"] = format_aeat_date(doc.to_date)
		filters["FechaExpedicionFactura"] = {"RangoFechaExpedicion": rango}

	return filters


def _client(company: str) -> Any:
	"""Cliente AEAT (VeriFactu) de la empresa: entorno según su modo
	operativo (Pruebas/Producción), mismo criterio que el driver de
	remisión. La factory conmutada por el flag del site `es_aeat_mock`
	deja inyectar el mock en tests (se parchea este símbolo)."""
	mode = frappe.db.get_value("Company", company, "es_verifactu_test_mode")
	return build_client(
		service=VERIFACTU_PURPOSE,
		environment=ENV_PRODUCTION if mode == PRODUCTION_MODE else ENV_TEST,
		company=company,
	)


def _persist(doc: Document, response: dict) -> None:
	"""Persiste la respuesta (spec 04 §10): crudo en `result`
	(auditable) + una fila en `lines` por registro devuelto, con su
	identificación AEAT y su estado consolidado."""
	doc.result = frappe.as_json(response)
	doc.set("lines", [])
	for record in _records_from(response):
		state = record.get("EstadoRegistro") or {}
		doc.append(
			"lines",
			{
				"invoice_id": frappe.as_json(record.get("IDFactura") or {}),
				"state": state.get("EstadoRegistro"),
				"error_code": _text(state.get("CodigoErrorRegistro")),
				"error_description": state.get("DescripcionErrorRegistro"),
				"last_modified_at": _text(state.get("TimestampUltimaModificacion")),
				"record_data": frappe.as_json(record.get("DatosRegistroFacturacion") or {}),
			},
		)
	doc.save(ignore_permissions=True)


def _records_from(response: dict) -> list[dict]:
	"""Registros devueltos por la AEAT (clave del WSDL); defensa si un
	único elemento serializara sin lista."""
	records = response.get(RECORDS_KEY) or []
	if isinstance(records, dict):
		records = [records]
	return [record for record in records if isinstance(record, dict)]


def _text(value: Any) -> str | None:
	"""Código/timestamp → str serializable; vacío → None."""
	if value in (None, ""):
		return None
	return str(value)
