# doc_events de Company (spec 04 §2.1): puerta de activación de VeriFactu.
#
# Handler barato cuando no aplica (doc 12 §2): sin enabled solo se paga UNA
# lectura indexada (fecha de activación + NOI persistidos) para los guards que
# corren SIEMPRE. El NIF de la compañía ya lo valida nif/party.validate en el
# MISMO evento ( corre antes: doc_events en lista); aquí se cierra la compuerta
# de ACTIVACIÓN: presente, válido y ÚNICO en el site (respuestas AEAT se
# enrutan por NIF del emisor — sin unicidad llegan a la empresa equivocada).

from __future__ import annotations

import base64
import hashlib

import frappe
from frappe.model.document import Document

from erpnext_spain.aeat.utils import require_credential
from erpnext_spain.nif import validator

DOCTYPE = "Company"
SERIES_FIELD = "es_invoice_series"

# Lote máximo por envío que admite la AEAT (spec 04 §2.1/§8).
BATCH_LIMIT_MAX = 1000

VERIFACTU_PURPOSE = "VeriFactu"


def validate(doc: Document, method: str | None = None) -> None:
	previous = _previous_state(doc)

	_freeze_activation_date(doc, previous)
	_validate_limits(doc)

	if doc.get("es_verifactu_enabled"):
		_validate_activation(doc)

	_ensure_noi(doc, previous)


# --- guards que corren SIEMPRE (con o sin VeriFactu activo) ---


def _freeze_activation_date(doc: Document, previous: dict | None) -> None:
	"""La fecha de activación se congela en cuanto la empresa tiene CUALQUIER
	registro de facturación: moverla invalidaría la semántica de los registros
	ya emitidos (spec 04 §2.1). La desactivación NO está bloqueada por esto
	(los pendientes siguen drenándose, spec 04 §8)."""
	old = _as_date_str((previous or {}).get("es_verifactu_activation_date"))
	if not old:
		return

	new = _as_date_str(doc.get("es_verifactu_activation_date"))
	if new != old and _has_records(doc.name):
		frappe.throw(
			f"No se puede cambiar la fecha de activación de VeriFactu de {doc.name}"
			f" («{old}» → «{new}»): la empresa ya tiene registros de"
			" facturación emitidos con esa semántica y moverla invalidaría el"
			" libro (spec 04 §2.1). Remedio: mantenga la fecha original; para"
			" dejar de emitir registros nuevos, desactive VeriFactu (los"
			" registros pendientes seguirán remitiéndose a la AEAT).",
			frappe.ValidationError,
		)


def _validate_limits(doc: Document) -> None:
	"""El límite de lote respeta el máximo de la AEAT aunque la empresa no
	esté activa: el valor queda persistido y la remisión lo usa (spec 04 §8)."""
	limit = doc.get("es_verifactu_batch_limit")
	if limit and limit > BATCH_LIMIT_MAX:
		frappe.throw(
			f"El límite de lote de remisión de {doc.name} es {limit}: la AEAT"
			f" admite como máximo {BATCH_LIMIT_MAX} registros por envío (spec 04"
			" §8). Remedio: fije un valor menor o igual a {BATCH_LIMIT_MAX} (el"
			" valor por defecto).",
			frappe.ValidationError,
		)


# --- compuerta de activación (solo con el interruptor activo) ---


def _validate_activation(doc: Document) -> None:
	"""Validaciones duras al activar (o al guardar activa). Cada throw incluye
	el remedio (doc 12 §2)."""
	tax_id = (doc.get("tax_id") or "").strip()

	if not tax_id:
		frappe.throw(
			f"{doc.name} no puede activar VeriFactu sin NIF: el NIF del emisor"
			" identifica los registros ante la AEAT y sin él las respuestas no"
			" se pueden enrutar (spec 04 §2.1). Remedio: complete el campo NIF"
			" de la compañía y reintente la activación.",
			frappe.ValidationError,
		)

	try:
		validator.validate_spanish_tax_id(tax_id)
	except validator.InvalidTaxID as exc:
		frappe.throw(
			f"El NIF «{tax_id}» de {doc.name} no es válido y VeriFactu no se"
			" puede activar con un NIF incorrecto: el emisor debe estar"
			f" correctamente identificado ante la AEAT. {exc} Remedio: corrija el"
			" NIF de la compañía y reintente la activación.",
			frappe.ValidationError,
		)

	duplicate_filters = {"tax_id": tax_id}
	if doc.name:
		duplicate_filters["name"] = ("!=", doc.name)
	duplicate = frappe.db.exists("Company", duplicate_filters)
	if duplicate:
		frappe.throw(
			f"El NIF «{tax_id}» ya pertenece a otra empresa del site"
			f" ({duplicate}): las respuestas de la AEAT se enrutan por NIF del"
			" emisor y dos empresas no pueden compartir NIF (spec 04 §2.1)."
			" Remedio: asigne a cada empresa su NIF propio; si {duplicate} es"
			" un dato de prueba, corrija su NIF.",
			frappe.ValidationError,
		)

	require_credential(doc.name, "activar VeriFactu (la remisión exige TLS mutua con la AEAT)")

	if not doc.get("es_verifactu_activation_date"):
		frappe.throw(
			f"Falta la fecha de activación de VeriFactu de {doc.name}: las"
			" facturas emitidas (FechaExpedicion) desde esa fecha generan"
			" registro y las anteriores son legado pre-VeriFactu (spec 04"
			" §2.1). Remedio: indique la fecha desde la que la empresa emite"
			" con registro VeriFactu.",
			frappe.ValidationError,
		)

	draft_series = (doc.get("es_draft_series") or "").strip()
	if not draft_series:
		frappe.throw(
			f"Falta la serie de borradores de {doc.name}: con VeriFactu activo,"
			" los borradores usan un nombre temporal y el número fiscal solo se"
			" consume al emitir (spec 04 §4). Remedio: indique un patrón de"
			" numeración para borradores que no comparta prefijo con las series"
			" mapeadas, p. ej. «BORRADOR-.#####».",
			frappe.ValidationError,
		)

	prefixes = _validate_series(doc)

	if _series_prefix(draft_series) in prefixes:
		frappe.throw(
			f"La serie de borradores «{draft_series}» colisiona con una serie"
			" mapeada: el contador de numeración de ERPNext es global por"
			" prefijo y la colisión quemaría números de la serie fiscal (spec"
			" 04 §2.1). Remedio: use un prefijo distinto para los borradores,"
			" p. ej. «BORRADOR-.#####».",
			frappe.ValidationError,
		)


def _validate_series(doc: Document) -> set[str]:
	"""Biyección serie↔tipo (una serie por tipo, un tipo por serie) y no
	compartición de series entre empresas. Devuelve los prefijos mapeados
	(la clave del contador tabSeries)."""
	prefixes: dict[str, str] = {}
	types: dict[str, str] = {}

	for row in doc.get(SERIES_FIELD) or []:
		series = (row.get("series") or "").strip()
		invoice_type = (row.get("invoice_type") or "").strip()
		if not series or not invoice_type:
			continue  # los reqd de la child los valida el framework

		prefix = _series_prefix(series)
		if prefix in prefixes:
			frappe.throw(
				f"La serie «{series}» está duplicada en el mapeo de series de"
				f" {doc.name}: el mapeo serie↔tipo es una biyección, una serie"
				" por tipo y un tipo por serie (spec 04 §2.1). Remedio: quite"
				" la fila duplicada del mapeo.",
				frappe.ValidationError,
			)
		prefixes[prefix] = series

		if invoice_type in types:
			frappe.throw(
				f"El tipo de factura «{invoice_type}» está duplicado en el mapeo de"
				f" series de {doc.name} (series «{types[invoice_type]}» y «{series}»): el"
				" mapeo serie↔tipo es una biyección (spec 04 §2.1). Remedio:"
				" asigne un único tipo por serie.",
				frappe.ValidationError,
			)
		types[invoice_type] = series

	if prefixes and doc.name:
		for other in frappe.get_all(
			"ES Invoice Series",
			filters={"parenttype": DOCTYPE, "parent": ("!=", doc.name)},
			fields=["series", "parent"],
		):
			other_prefix = _series_prefix(other.series)
			if other_prefix in prefixes:
				frappe.throw(
					f"La serie «{prefixes[other_prefix]}» (prefijo"
					f" «{other_prefix}») ya la usa la empresa {other.parent}: el"
					" contador de series de ERPNext es global por prefijo, sin"
					" dimensión empresa — dos empresas con la misma serie"
					" intercalarían números y romperían la correlatividad de"
					" ambas (spec 04 §2.1). Remedio: asigne a esta empresa un"
					" prefijo de serie propio.",
					frappe.ValidationError,
				)

	return set(prefixes)


# --- NOI (Número de Identificación de la instalación) ---


def _ensure_noi(doc: Document, previous: dict | None) -> None:
	"""NOI: SHA-256 en Base32 sobre (nombre del site, nombre de la empresa),
	derivado UNA VEZ al activar y JAMÁS recalculado — la identidad de la
	instalación ante la AEAT debe ser estable (spec 04 §2.1). El campo es
	read_only en el form; aquí se restaura el valor persistido ante cualquier
	manipulación por API."""
	persisted_noi = (previous or {}).get("es_verifactu_noi")
	if persisted_noi:
		doc.es_verifactu_noi = persisted_noi
	elif doc.get("es_verifactu_enabled") and doc.name:
		doc.es_verifactu_noi = _derive_noi(doc.name)


def _derive_noi(company: str) -> str:
	"""Derivación determinista: misma empresa+mismo site → mismo NOI;
	empresas distintas → NOI distinto (garantizado por el input)."""
	digest = hashlib.sha256(f"{frappe.local.site}|{company}".encode()).digest()
	return base64.b32encode(digest).decode().rstrip("=")


# --- helpers ---


def _previous_state(doc: Document) -> dict | None:
	"""Valores persistidos de los campos con guards permanentes, en UNA lectura.
	None para empresas nuevas (no hay estado previo que congelar)."""
	if doc.is_new() or not doc.name:
		return None
	return frappe.db.get_value(
		DOCTYPE,
		doc.name,
		["es_verifactu_activation_date", "es_verifactu_noi"],
		as_dict=True,
	)


def _series_prefix(series: str) -> str:
	"""Prefijo estático de un patrón de numeración de ERPNext: todo lo que
	precede a la primera parte dinámica («#####», «.YYYY.», ...). Es la clave
	del contador global tabSeries (naming.getseries), SIN dimensión empresa:
	por eso dos empresas no pueden compartir prefijo."""
	return (series or "").split(".", 1)[0]


def _as_date_str(value) -> str | None:
	"""Normaliza a «YYYY-MM-DD»: el valor del doc es str, pero db.get_value
	devuelve datetime.date para columnas Date — sin normalizar, la comparación
	de congelación daría distinto siempre."""
	if not value:
		return None
	return str(value)[:10]


def _has_records(company: str | None) -> bool:
	from erpnext_spain.es_verifactu.doctype.es_verifactu_billing_record.es_verifactu_billing_record import (
		has_records,
	)

	return has_records(company)
