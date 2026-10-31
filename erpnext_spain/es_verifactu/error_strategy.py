# Estrategia por código de error AEAT — lote 5b (spec 04 §3 + §9).
#
# Se aplica cuando el procesador de respuestas del driver (lote 5a) marca un
# registro del libro Incorrecto o AceptadoConErrores CON código de error:
# el mapa en código (extendible) decide qué hacer por código, y lo
# DESCONOCIDO nunca revienta el drenaje (nunc cras: log + notificación).
#
# Estrategias (semántica espejo de la referencia `spanish_compliance/
# verifactu/aeat_lib/aeat_data_adapter.py` get_error_resolution_strategy,
# códigos verificados contra errores.properties de la AEAT):
#
# - Reintento: error transitorio de la AEAT (p. ej. 4108/4110) → se REENVÍA
#   el Alta tal cual: registro NUEVO encadenado con flag `prior_rejection`
#   (el original JAMÁS se edita — libro inmutable, spec 04 §2.2).
# - Subsanación automática: el dato se puede regenerar sin intervención
#   (2004: timestamp fuera de rango — regenerar produce un
#   FechaHoraHusoGenRegistro fresco) → registro NUEVO con flag
#   `is_correction`.
# - Subsanación manual: el error exige corrección humana → se deriva
#   `curable=1` en el registro (lo consume el informe «Rectifiable
#   Invoices» y la validación de rectify()) y se notifica la incidencia
#   por los DOS canales (roles → Notification Log + es_incidents_email).
# - Desconocido: código fuera del mapa → frappe.log_error + notificación
#   (contactar con el equipo de desarrollo).
#
# La REEMISIÓN (reintento/subsanación automática) sale SIEMPRE del estado
# ACTUAL de la factura vía emission.regenerate_issuance, bajo el cerrojo de
# cadena — nada de duplicar la lógica de encadenamiento aquí.
#
# Idempotencia: la guarda por respuesta vive en el driver (procesar la
# MISMA respuesta dos veces no dispara la estrategia dos veces).

from __future__ import annotations

import copy
from typing import Any

import frappe

from erpnext_spain.aeat.utils import notify_roles
from erpnext_spain.es_verifactu.emission import regenerate_issuance

LEDGER_DOCTYPE = "ES Verifactu Billing Record"

STRATEGY_RETRY = "Retry"
STRATEGY_AUTO_RECTIFICATION = "AutoRectification"
STRATEGY_MANUAL_RECTIFICATION = "ManualRectification"
STRATEGY_UNKNOWN = "Unknown"

# Mapa de códigos verificados por estrategia (errores.properties de la AEAT,
# semilla de la referencia — extendible: alta de nuevas claves sin tocar el
# dispatcher). Códigos ausentes → Desconocido.
CODES_BY_STRATEGY: dict[str, tuple[int, ...]] = {
	STRATEGY_RETRY: (4108, 4110, 4111, 4128, 4134, 3501),
	STRATEGY_AUTO_RECTIFICATION: (2004,),
	# 1112 «FechaExpedicionFactura superior a la fecha actual» (verificado en
	# vivo contra el entorno de pruebas): la fecha ya no es futura al
	# rectificar → rectify() regenera del estado ACTUAL de la factura y
	# reenvía con timestamp fresco.
	STRATEGY_MANUAL_RECTIFICATION: (3000, 2001, 4107, 1109, 1110, 1112),
}

_STRATEGY_BY_CODE: dict[int, str] = {
	code: strategy for strategy, codes in CODES_BY_STRATEGY.items() for code in codes
}

# Estados desde los que la reemisión tiene sentido (spec 04 §3): solo se
# reenvía lo que la AEAT NO dio por bueno.
RESUBMITTABLE_STATES = ("Incorrecto", "AceptadoConErrores")

# Campos del dialog de subsanación por código de error (patrón
# VERIFACTU_ERROR_FIELDS de la referencia; el glue JS llega en el lote 6):
# descriptores estáticos de frappe.ui.dialog — remedio + campos a corregir.
DIALOG_FIELDS_BY_ERROR: dict[int, list[dict]] = {
	3000: [
		{
			"fieldtype": "HTML",
			"options": (
				'<div class="alert alert-danger"><strong>Error 3000: registro de'
				" facturación duplicado.</strong><br>Ya existe en la AEAT un registro"
				" con el mismo número de serie. Corrija la numeración de la factura"
				" (la serie fiscal no debe reutilizarse) y vuelva a remitir."
				"</div>"
			),
		},
		{"fieldtype": "Section Break", "label": "Acción correctiva"},
		{
			"fieldname": "series_number",
			"label": "Número de serie de la factura",
			"fieldtype": "Data",
			"read_only": 1,
		},
	],
	1239: [
		{
			"fieldtype": "HTML",
			"options": (
				'<div class="alert alert-danger"><strong>Error 1239: bloque'
				" Destinatario erróneo.</strong><br>Actualice los datos fiscales del"
				" cliente (NIF/denominación) en su ficha y en la factura, y subsane:"
				" el registro se regenera desde el estado actual de la factura."
				"</div>"
			),
		},
		{"fieldtype": "Section Break", "label": "Acción correctiva"},
		{
			"fieldname": "customer",
			"label": "Cliente",
			"fieldtype": "Link",
			"options": "Customer",
			"read_only": 1,
		},
		{"fieldname": "customer_tax_id", "label": "N.I.F. del cliente", "fieldtype": "Data", "read_only": 1},
	],
}

DEFAULT_DIALOG_FIELDS: list[dict] = [
	{
		"fieldtype": "HTML",
		"options": (
			'<div class="alert alert-danger"><strong>Error no contemplado.</strong>'
			"<br>Corrija la factura según la descripción del error de la AEAT y"
			" subsane: el registro se regenera desde el estado actual de la"
			" factura. Tenga cuidado: los valores remitidos tienen relevancia"
			" fiscal.</div>"
		),
	},
	{"fieldtype": "Section Break", "label": "Acción correctiva"},
	{"fieldname": "error_code", "label": "Código de error AEAT", "fieldtype": "Data", "read_only": 1},
	{
		"fieldname": "error_description",
		"label": "Descripción del error AEAT",
		"fieldtype": "Small Text",
		"read_only": 1,
	},
]


def strategy_for(error_code: Any) -> str:
	"""Estrategia para un código de error AEAT (str/int); desconocido o
	vacío → Desconocido (nunc cras: se registra y notifica, jamás revienta)."""
	try:
		code = int(str(error_code).strip())
	except TypeError, ValueError:
		return STRATEGY_UNKNOWN
	return _STRATEGY_BY_CODE.get(code, STRATEGY_UNKNOWN)


def is_curable(error_code: Any) -> bool:
	"""¿El código exige subsanación MANUAL? (deriva el flag `curable` del
	registro, spec 04 §9 — lo consume el informe y la validación de
	rectify()). Las automáticas y los reintentos no esperan al usuario."""
	return strategy_for(error_code) == STRATEGY_MANUAL_RECTIFICATION


def dialog_fields(error_code: Any) -> list[dict]:
	"""Descriptores del dialog de subsanación para un código (patrón
	VERIFACTU_ERROR_FIELDS de la referencia; defaults por lote 6). Copia
	profunda: el llamador puede mutar la lista (la referencia añade
	«default» en sitio) sin envenenar el mapa."""
	try:
		code = int(str(error_code).strip())
	except TypeError, ValueError:
		code = None
	return copy.deepcopy(DIALOG_FIELDS_BY_ERROR.get(code, DEFAULT_DIALOG_FIELDS))


def apply_strategy(record_name: str, error_code: str | None, description: str | None) -> None:
	"""Aplica la estrategia del código de error a un registro del libro que
	acaba de transicionar a Incorrecto/AceptadoConErrores (la llama el
	procesador del driver; NUNCA lanza — el driver aísla por empresa, pero el
	procesador no revienta el lote si puede evitarlo, spec 13 §5).

	Cuando la reemisión automática no procede (registro sin factura, o
	reintento sobre un registro ya aceptado con errores), el caso BAJA a
	subsanación manual: el humano ve el aviso y decide.
	"""
	try:
		_apply_internal(record_name, error_code, description)
	except Exception:
		frappe.log_error(
			title=f"VeriFactu: fallo aplicando la estrategia del error {error_code}",
			message=f"Registro {record_name} de {error_code!r}:\n{frappe.get_traceback()}",
		)


def _apply_internal(record_name: str, error_code: str | None, description: str | None) -> None:
	record = frappe.get_doc(LEDGER_DOCTYPE, record_name)
	strategy = strategy_for(error_code)
	resubmittable = (
		record.record_type == "RegistroAlta"
		and bool(record.sales_invoice)
		and record.status in RESUBMITTABLE_STATES
	)

	if strategy == STRATEGY_RETRY and resubmittable:
		# Reenvío del alta tal cual (spec 04 §3): registro NUEVO con flag
		# prior_rejection, mismo estado actual de la factura.
		regenerate_issuance(record.sales_invoice, prior_rejection=True)
		return

	if strategy == STRATEGY_AUTO_RECTIFICATION and resubmittable:
		# Regeneración corregida sin intervención (2004: timestamp fresco,
		# sale de now_aeat vía regenerate_issuance): registro NUEVO con flag
		# is_correction.
		regenerate_issuance(record.sales_invoice, correction=True)
		return

	if strategy == STRATEGY_UNKNOWN:
		_unknown(record, error_code, description)
		return

	# Subsanación manual (y degradación de las automáticas que no pueden
	# reemitir): deriva el flag y notifica por los DOS canales.
	_manual_rectification(record, error_code, description)


def _manual_rectification(record, error_code: str | None, description: str | None) -> None:
	"""Deriva `curable=1` (la vía del procesador: db.set_value sin pasar
	por el validate del libro — el registro ya es terminal y congelado,
	spec 04 §2.2/§3) y notifica la incidencia con remedio (spec 04 §9)."""
	frappe.db.set_value(LEDGER_DOCTYPE, record.name, "curable", 1, update_modified=False)
	invoice = record.sales_invoice or "(sin factura)"
	notify_roles(
		record.company,
		f"VeriFactu: la factura {invoice} requiere subsanación manual (error {error_code} de la AEAT)",
		f"El registro {record.record_type} de la factura {invoice} de"
		f" {record.company} fue rechazado por la AEAT con el código"
		f" {error_code}: {description or '(sin descripción)'}. Remedio:"
		" corrija la factura (los campos implicados dependen del código de"
		" error) y ejecute la subsanación desde la factura — se generará un"
		" registro nuevo encadenado con el indicador «Subsanación». La"
		" factura aparece en el informe «Rectifiable Invoices» del módulo ES"
		" VeriFactu, ordenado por cadena.",
	)


def _unknown(record, error_code: str | None, description: str | None) -> None:
	"""Código fuera del mapa (nunc cras): constancia en Error Log +
	notificación por los dos canales — contactar con el equipo de
	desarrollo, que decide la estrategia y la da de alta en el mapa."""
	invoice = record.sales_invoice or "(sin factura)"
	frappe.log_error(
		title=f"VeriFactu: código de error AEAT no contemplado ({error_code})",
		message=(
			f"El registro {record.name} ({record.record_type} de la factura"
			f" {invoice} de {record.company}) llegó con el código de error"
			f" {error_code!r} ({description or 'sin descripción'}), que NO está"
			" en erpnext_spain.es_verifactu.error_strategy.CODES_BY_STRATEGY."
			" Remedio: el equipo de desarrollo debe clasificar el código en el"
			" mapa (reintento / subsanación automática / manual) y las"
			" instalaciones se actualizan."
		),
	)
	notify_roles(
		record.company,
		f"VeriFactu: error desconocido de la AEAT en la factura {invoice} ({error_code})",
		f"El registro de facturación de la factura {invoice} de"
		f" {record.company} recibió de la AEAT el código de error"
		f" {error_code} ({description or 'sin descripción'}), que el sistema"
		" no sabe resolver automáticamente. Remedio: contacte con su equipo"
		" de desarrollo o proveedor del sistema con el código y la descripción"
		" del error para clasificarlo y poder subsanarlo.",
	)
