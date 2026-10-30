# Helpers Jinja para el Print Format de factura VeriFactu — lote 6a (spec 04
# §11, doc 12 §14): expuestos al entorno de plantillas de impresión vía el hook
# `jinja.methods` (patrón India Compliance, mismo registro que la referencia).
#
# - get_verifactu_qr_url: URL de validación ValidarQR de la AEAT (la base según
#   el MODO de la factura) — también la consume el formato para imprimir el
#   ENLACE legible junto al QR.
# - get_verifactu_qr_code: SVG (segno, cero dependencias pesadas) de esa URL.
# - get_verifactu_breakup: desglose IVA formateado para la tabla de impuestos.
# - get_es_display_name: denominación spec 14 «NombreComercial (RazónSocial)»
#   — SOLO display: jamás fluye a la AEAT (el RegistroAlta lleva la razón
#   social del maestro).
#
# NOTA NORMATIVA PENDIENTE (spec 04 «Dudas»): el formato exacto del contenido
# del QR está pendiente de verificación contra la Orden HAC/1177/2024 — se
# espeja la construcción de la referencia validada en su entorno de pruebas
# (nif, fecha, importe, numserie).

from __future__ import annotations

import io
import urllib.parse

import frappe
import segno

from erpnext_spain.aeat.utils import format_aeat_date
from erpnext_spain.es_verifactu.emission import VERIFACTU_MODE, VERIFACTU_TEST_MODE
from erpnext_spain.es_verifactu.utils.data_adapter import _format_amount
from erpnext_spain.es_verifactu.utils import data_adapter

# Bases del endpoint ValidarQR de la AEAT (verificadas contra la referencia
# `spanish_compliance/overrides/sales_invoice.py` es_verifactu_sales_invoice_qr):
# el dominio REAL de producción es agenciatributaria.gob.es (www2); el
# entorno de pruebas de la AEAT cuelga de prewww2.aeat.es. La URL del QR NO es
# el WSDL de ES Settings (ese es el endpoint SOAP de remisión).
QR_URL_BASE_PRUEBAS = "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR?"
QR_URL_BASE_PRODUCCION = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR?"

# Escala del SVG (módulos por punto): tamaño de impresión suficiente para el
# escaneo del código sin inflar el HTML.
QR_SCALE = 4


def get_verifactu_qr_url(doc) -> str:
	"""URL de validación ValidarQR de la AEAT para la factura.

	Parámetros en el orden exacto del spec 04 §11 (nif, fecha, importe,
	numserie — misma construcción que la referencia): nif = NIF del EMISOR
	(compañía), fecha = FechaExpedicion dd-mm-aaaa, importe = total redondeado
	(formato de monto congelado del adaptador: «121.0», sin coma española) y
	numserie = nombre final de la factura URL-encodeado (las series con «/»
	etc. viajan escapadas).

	La BASE la decide el MODO OPERATIVO: snapshot congelado de la factura
	(`es_verifactu_mode`, spec 04 §2.3 — una factura emitida en producción
	sigue apuntando a producción aunque la compañía cambie después) con
	fallback al estado ACTUAL de la compañía para facturas sin snapshot
	(borradores de una compañía activa). Sin VeriFactu → cadena vacía (sin
	QR: no hay nada validable en la AEAT).
	"""
	mode = _verifactu_mode(doc)
	if mode == VERIFACTU_TEST_MODE:
		base = QR_URL_BASE_PRUEBAS
	elif mode == VERIFACTU_MODE:
		base = QR_URL_BASE_PRODUCCION
	else:
		return ""

	issuer_nif = frappe.db.get_value("Company", doc.company, "tax_id") or ""
	issue_date = format_aeat_date(doc.get("posting_date"))
	total_amount = _format_amount(doc.get("rounded_total") or 0)
	series_number = urllib.parse.quote(doc.name or "", safe="")

	return f"{base}nif={issuer_nif}&fecha={issue_date}&importe={total_amount}&numserie={series_number}"


def get_verifactu_qr_code(doc) -> str:
	"""SVG del QR de validación de la factura (segno, inline sin declaración
	XML — imprimible tal cual dentro del HTML del formato). Cadena vacía
	cuando la factura no es VeriFactu (la plantilla no muestra el bloque QR)."""
	url = get_verifactu_qr_url(doc)
	if not url:
		return ""

	buffer = io.BytesIO()
	segno.make(url).save(buffer, kind="svg", scale=QR_SCALE, xmldecl=False)
	return buffer.getvalue().decode("utf-8")


def get_verifactu_breakup(doc) -> list[dict]:
	"""Desglose IVA formateado para la tabla de impuestos de la plantilla.

	Reutiliza `data_adapter.get_spain_tax_breakup` (el MISMO contrato de
	spec 04 §7 que alimenta el RegistroAlta — una sola fuente de verdad del
	desglose) y le añade el formato de display: importes con fmt_money de la
	moneda de la factura. Los impuestos que el contrato aún no contempla
	(IRPF, recargos — tarea del módulo 07) NO revientan la impresión: se
	omite la fila (impresión degradada, no rota)."""
	try:
		rows = data_adapter.get_spain_tax_breakup(doc)
	except ValueError:
		return []

	currency = doc.get("currency")
	return [
		{
			"tax": row["tax_type"],
			"rate": f'{row["tax_rate"]}%',
			# v16: fmt_money(amount, precision, currency, ...) — la moneda va
			# POR CLAVE (posicional caería en precision).
			"base": frappe.utils.fmt_money(row["taxable_base"], currency=currency),
			"tax_amount": frappe.utils.fmt_money(row["tax_amount"], currency=currency),
		}
		for row in rows
	]


def get_es_display_name(doc, party_field: str = "customer") -> str:
	"""Denominación del tercero para display (spec 14): «NombreComercial
	(RazónSocial)» cuando el maestro trae `es_trade_name`, si no la
	razón social. Solo presentación — el RegistroAlta SIEMPRE viaja con la
	razón social del maestro (spec 14 §2: lo que fluye a la AEAT es el NIF,
	el nombre comercial no se remite)."""
	doctype = party_field.capitalize()
	link = doc.get(party_field)
	legal_name = doc.get(f"{party_field}_name") or ""
	trade_name = ""

	if link and frappe.db.exists(doctype, link):
		data = frappe.db.get_value(
			doctype, link, ["es_trade_name", f"{party_field}_name"], as_dict=True
		)
		if data:
			trade_name = data.get("es_trade_name") or ""
			legal_name = data.get(f"{party_field}_name") or legal_name

	if trade_name and trade_name != legal_name:
		return f"{trade_name} ({legal_name})"
	return legal_name


def _verifactu_mode(doc) -> str:
	"""Modo operativo de la factura para el QR: snapshot congelado
	(`es_verifactu_mode`) si existe; si no, estado ACTUAL de la compañía
	(activa en pruebas → «Verifactu en pruebas»; activa en producción →
	«Verifactu»; inactiva → cadena vacía: sin VeriFactu no hay QR)."""
	mode = (doc.get("es_verifactu_mode") or "").strip()
	if mode:
		return mode

	company_conf = frappe.db.get_value(
		"Company", doc.get("company"), ["es_verifactu_enabled", "es_verifactu_test_mode"], as_dict=True
	)
	if not company_conf or not company_conf.es_verifactu_enabled:
		return ""
	return VERIFACTU_TEST_MODE if company_conf.es_verifactu_test_mode == "Pruebas" else VERIFACTU_MODE
