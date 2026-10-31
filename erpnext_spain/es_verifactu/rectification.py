# Subsanación MANUAL VeriFactu — lote 5b (spec 04 §9).
#
# `rectify` (whitelisted, permiso explícito por empresa+propósito — doc 12
# §18): valida que el ÚLTIMO registro de la factura sea el marcado
# «Subsanable» por la estrategia de errores (lote 5b/error_strategy.py),
# respeta la SUBSANACIÓN EN ORDEN cuando la compañía la exige, y regenera
# el Alta desde el estado ACTUAL de la factura
# (emission.regenerate_issuance): un registro NUEVO encadenado con los
# indicadores Subsanación/RechazoPrevio/SinRegistroPrevio — el registro
# original JAMÁS se edita (libro inmutable, spec 04 §2.2) y la factura
# vuelve a «Pendiente Envío».
#
# El glue JS del dialog (sales_invoice.js, lote 6a) consume
# get_rectification_state + get_dialog_fields → rectify.

from __future__ import annotations

import frappe

from erpnext_spain.aeat.utils import has_aeat_permission
from erpnext_spain.es_verifactu.emission import (
	INVOICE_STATUS_PENDING_SEND,
	VERIFACTU_PURPOSE,
	regenerate_issuance,
)
from erpnext_spain.es_verifactu.error_strategy import dialog_fields

LEDGER_DOCTYPE = "ES Verifactu Billing Record"

# Estados del registro que habilitan la subsanación manual (spec 04 §3):
# lo que la AEAT NO dio por Correcto y la estrategia marcó subsanable.
RECTIFIABLE_STATES = ("Incorrecto", "AceptadoConErrores")

# Estados que BLOQUEAN la subsanación en orden (spec 04 §9): pendientes y
# erróneos — el SIF procesa la cadena en orden.
BLOCKING_STATES = ("PendienteEnvio", "Incorrecto")


@frappe.whitelist(methods=["POST"])
def rectify(invoice: str) -> str:
	"""Subsana la factura: regenera su RegistroAlta desde el estado ACTUAL
	(los campos corregidos ya viven en la factura) y lo deja encadenado
	como registro nuevo PendienteEnvio. Devuelve el docname del registro
	creado (el dialog del lote 6 lo usa para refrescar).

	Guardas (con remedio en el mensaje):
	1. Permiso explícito (empresa, VeriFactu) — doc 12 §18.
	2. El ÚLTIMO registro de la factura es el marcado «Subsanable».
	3. Subsanación en orden (si la compañía la exige): solo se subsana la
	   factura cuyo registro erróneo sea el más ANTIGUO pendiente/erróneo
	   del SIF.
	"""
	header = frappe.db.get_value("Sales Invoice", invoice, ["company"], as_dict=True)
	if not header:
		frappe.throw(
			f"La factura {invoice} no existe: no hay nada que subsanar.",
			frappe.DoesNotExistError,
		)
	company = header.company

	if not has_aeat_permission(frappe.session.user, company, VERIFACTU_PURPOSE):
		frappe.throw(
			f"El usuario {frappe.session.user} no tiene permiso AEAT de {company}"
			" para el propósito VeriFactu: la subsanación reenvía el registro a"
			" la AEAT y exige el chequeo explícito por empresa+propósito (doc 12"
			" §18). Remedio: conceda al usuario un rol con permiso (roles de"
			" notificación de la compañía o, en su defecto, Accounts Manager)"
			" y acceso de lectura a la compañía.",
			frappe.PermissionError,
		)

	erroneous = _rectifiable_record(invoice)
	_validate_order(company, erroneous)

	new_name = regenerate_issuance(
		invoice,
		correction=True,
		prior_rejection=_had_prior_rejection(invoice),
	)

	# El flag «Subsanable» marca la cura PENDIENTE: subsanada, el registro
	# sale del informe «Rectifiable Invoices» (spec 04 §9). La vía del
	# procesador (db.set_value): el registro es terminal y congelado.
	frappe.db.set_value(
		LEDGER_DOCTYPE, erroneous.name, "curable", 0, update_modified=False
	)
	# La factura vuelve al outbox: su registro nuevo viaja PendienteEnvio.
	frappe.db.set_value(
		"Sales Invoice", invoice, "es_verifactu_status", INVOICE_STATUS_PENDING_SEND,
		update_modified=False,
	)
	return new_name


@frappe.whitelist()
def get_dialog_fields(error_code: str) -> list[dict]:
	"""Campos del dialog de subsanación para un código de error AEAT (patrón
	VERIFACTU_ERROR_FIELDS de la referencia; el glue JS llega en el lote 6).
	Descriptores estáticos con el remedio y los campos a corregir — sin
	comunicación con la AEAT, por eso sin gate de permiso adicional al del
	propio endpoint."""
	return dialog_fields(error_code)


@frappe.whitelist()
def get_rectification_state(invoice: str) -> dict:
	"""Estado de subsanación de la factura para el glue JS del form (lote 6a,
	spec 04 §9): ¿su ÚLTIMO registro del libro está marcado «Subsanable»? Con
	el código y la descripción del error — alimentan el dialog
	(get_dialog_fields) y sus defaults.

	Lectura del libro local (sin comunicación con la AEAT): permiso de
	lectura sobre la factura, la misma frontera de api.verifactu_status
	(doc 12 §18). MISMA condición que validará rectify(): el último registro
	por cadena con el flag y estado reemisible — el botón no miente."""
	if not frappe.has_permission("Sales Invoice", "read", doc=invoice):
		frappe.throw(
			f"No tiene permiso de lectura sobre la factura {invoice}. Remedio:"
			" solicite el acceso pertinente al administrador del site.",
			frappe.PermissionError,
		)

	latest = frappe.get_all(
		LEDGER_DOCTYPE,
		filters={"sales_invoice": invoice},
		fields=["name", "status", "curable", "response_error_code", "response_error_msg"],
		order_by="chain_index desc",
		limit=1,
	)

	state = {"rectifiable": False, "error_code": None, "error_description": None}
	if not latest:
		return state

	record = latest[0]
	if record.curable and record.status in RECTIFIABLE_STATES:
		state = {
			"rectifiable": True,
			"error_code": record.response_error_code,
			"error_description": record.response_error_msg,
		}
	return state


def _rectifiable_record(invoice: str):
	"""Último registro de la factura por cadena y validación de que es el
	subsanable (la estrategia de errores lo marcó, spec 04 §9)."""
	latest = frappe.get_all(
		LEDGER_DOCTYPE,
		filters={"sales_invoice": invoice},
		fields=["name", "status", "curable", "chain_index", "sales_invoice"],
		order_by="chain_index desc",
		limit=1,
	)
	if not latest:
		frappe.throw(
			f"La factura {invoice} no tiene registros en el libro VeriFactu: no"
			" hay nada que subsanar. Remedio: verifique la factura — solo se"
			" subsanan facturas emitidas con registro remitido a la AEAT.",
			frappe.ValidationError,
		)
	record = latest[0]
	if not record.curable or record.status not in RECTIFIABLE_STATES:
		frappe.throw(
			f"La factura {invoice} no está pendiente de subsanación manual: su"
			f" último registro del libro ({record.name}, estado"
			f" «{record.status}») no está marcado «Subsanable» por el"
			" procesador de respuestas. Remedio: espere a que la AEAT procese"
			" el registro pendiente, o —si fue rechazado con un código que exige"
			" corrección— revise el informe «Rectifiable Invoices» (módulo ES"
			" VeriFactu) para localizar la factura que sí lo está.",
			frappe.ValidationError,
		)
	return record


def _validate_order(company: str, erroneous) -> None:
	"""Subsanación EN ORDEN (spec 04 §9): si `es_verifactu_mandatory_in_order_
	cure`, solo puede subsanarse la factura cuyo registro erróneo sea la
	FRONTERA del SIF (ORM: pendientes+incorrectos de la empresa ORDENADOS
	por chain_index — el primero es el único curable).

	Frontera = el candidato más antiguo SIN sucesor de su MISMA factura: un
	erróneo ya reintento/subsanado (su registro de cura viaja encadenado
	después) está supersanado y NO vuelve a bloquear — de lo contrario su
	original Incorrecto, congelado para siempre (libro inmutable),
	bloquearía la cadena eternamente. Un pendiente de OTRA factura sí
	bloquea: la AEAT procesa la cadena en orden."""
	if not frappe.db.get_value("Company", company, "es_verifactu_mandatory_in_order_cure"):
		return

	candidates = frappe.get_all(
		LEDGER_DOCTYPE,
		filters={"company": company, "status": ("in", BLOCKING_STATES)},
		fields=["name", "sales_invoice", "chain_index"],
		order_by="chain_index asc",
	)
	frontier = None
	for candidate in candidates:
		if candidate.sales_invoice and frappe.db.exists(
			LEDGER_DOCTYPE,
			{"sales_invoice": candidate.sales_invoice, "chain_index": (">", candidate.chain_index)},
		):
			continue  # su cura ya viaja en la cadena: supersanado
		frontier = candidate
		break

	if frontier and frontier.name != erroneous.name:
		frappe.throw(
			f"No puede subsanarse la factura {erroneous.sales_invoice}: la compañía"
			f" {company} exige SUBSANACIÓN EN ORDEN (spec 04 §9) y el registro más"
			" antiguo pendiente/erróneo sin curar del SIF es otro — el"
			f" {frontier.name} (cadena {frontier.chain_index}, factura"
			f" {frontier.sales_invoice or '(sin factura)'}). Remedio: espere a que"
			" la AEAT procese ese registro (si está pendiente) o subsane primero"
			" esa factura (el informe «Rectifiable Invoices» ordena las"
			" pendientes por cadena) y reintente después.",
			frappe.ValidationError,
		)


def _had_prior_rejection(invoice: str) -> bool:
	"""¿Algún registro PREVIO de la factura fue rechazado (Incorrecto)?
	Alimenta el indicador RechazoPrevio del registro de subsanación."""
	return bool(
		frappe.db.exists(
			LEDGER_DOCTYPE,
			{"sales_invoice": invoice, "status": "Incorrecto"},
		)
	)


def _had_prior_acceptance(invoice: str) -> bool:
	"""¿Algún registro PREVIO de la factura fue aceptado por la AEAT
	(Correcto/AceptadoConErrores)? Alimenta el indicador SinRegistroPrevio
	(«el original nunca llegó a registrarse», spec 04 §2.2/§9)."""
	return bool(
		frappe.db.exists(
			LEDGER_DOCTYPE,
			{"sales_invoice": invoice, "status": ("in", ("Correcto", "AceptadoConErrores"))},
		)
	)
