# Numeración fiscal al emitir, rectificativas y bloqueo de «amend» (spec 05 §1-§2).
#
# La numeración al emitir se activa en la compañía con `es_fiscal_numbering`
# (spec 01 §5) o, implícitamente, con VeriFactu activo (que ya la hacía en su
# propio before_submit, bajo el cerrojo de cadena). Sin ninguna de las dos, el
# autoname no asigna nombre y Frappe aplica la naming_series (H1).
#
# Sin VeriFactu, el renombrado del borrador a la serie de su tipo lo hace
# `before_submit` de este módulo. El contador de la serie (tabSeries) se lee y
# actualiza con bloqueo de fila dentro de la transacción del submit
# [verificado v16, frappe.model.naming.getseries]: dos emisiones simultáneas no
# repiten número y un submit que falla no consume número.

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from erpnext_spain.utils.gating import is_feature_enabled, is_verifactu_active

FISCAL_NUMBERING_FLAG = "es_fiscal_numbering"
METHOD_DIFFERENCES = "Por diferencias"
METHOD_SUBSTITUTION = "Por sustitución"
RECTIFICATION_METHODS = (METHOD_DIFFERENCES, METHOD_SUBSTITUTION)


def uses_fiscal_numbering(company: str | None) -> bool:
	"""¿Numera la compañía al emitir? Con `es_fiscal_numbering` o con VeriFactu."""
	return is_feature_enabled(company, FISCAL_NUMBERING_FLAG) or is_verifactu_active(company)


def is_rectification(doc: Document) -> bool:
	return bool(doc.get("is_return")) or (doc.get("es_invoice_type") or "").startswith("R")


# --- validate --------------------------------------------------------------------


def validate(doc: Document, method: str | None = None) -> None:
	if not uses_fiscal_numbering(doc.company):
		return
	if not is_verifactu_active(doc.company):
		# Con VeriFactu, el bloqueo y el tipo los valida emission.validate.
		block_amendment(doc)
	if doc.docstatus == 1:
		validate_rectification(doc)


def block_amendment(doc: Document) -> None:
	if doc.get("amended_from"):
		frappe.throw(
			_(
				"No se puede modificar («amend») la factura {0}: en España una factura emitida no se"
				" corrige ni se sustituye por otra con su número. Anule la original si procede y emita"
				" una factura rectificativa (botón «Crear → Devolución / Nota de crédito»)."
			).format(frappe.bold(doc.amended_from)),
			title=_("Emita una rectificativa"),
		)


def validate_rectification(doc: Document) -> None:
	if not is_rectification(doc):
		return
	invoice_type = doc.get("es_invoice_type") or ""
	if not invoice_type.startswith("R"):
		frappe.throw(
			_(
				"La factura {0} es rectificativa pero su tipo es {1}. Elija el tipo de rectificativa"
				" (R1 a R5) en el campo «Tipo de factura»: de él sale la serie."
			).format(frappe.bold(doc.name), frappe.bold(invoice_type or _("vacío"))),
			title=_("Tipo de rectificativa"),
		)
	if not (doc.get("es_rectification_reason") or "").strip():
		frappe.throw(
			_(
				"Indique el motivo de la rectificación de la factura {0} (campo «Motivo de la"
				" rectificación»). Es obligatorio en las facturas rectificativas (RD 1619/2012, art. 15)."
			).format(frappe.bold(doc.name)),
			title=_("Falta el motivo"),
		)
	if doc.get("es_rectification_method") == METHOD_SUBSTITUTION and is_verifactu_active(doc.company):
		frappe.throw(
			_(
				"La rectificación por sustitución aún no se puede comunicar a VeriFactu (exige los"
				" importes de la factura rectificada). Emítala por diferencias."
			),
			title=_("Método no admitido"),
		)


# --- before_submit ---------------------------------------------------------------


def before_submit(doc: Document, method: str | None = None) -> None:
	"""Renombra el borrador a la serie fiscal de su tipo (sin VeriFactu)."""
	if is_verifactu_active(doc.company) or not is_feature_enabled(doc.company, FISCAL_NUMBERING_FLAG):
		return
	from erpnext_spain.es_verifactu.invoice import is_draft_name

	draft_pattern = frappe.get_cached_value("Company", doc.company, "es_draft_series")
	if not is_draft_name(doc.name, draft_pattern):
		return  # nombre explícito (importación, migración): se respeta
	if not doc.get("es_invoice_type"):
		doc.es_invoice_type = "F1"
	# La fecha de expedición es la de emisión: así la correlatividad número-fecha
	# de cada serie queda garantizada por construcción (spec 05 §3).
	doc.posting_date = frappe.utils.today()
	from erpnext_spain.es_facturacion.pos import pos_series

	rename_to_fiscal_series(
		doc, pos_series(doc, doc.es_invoice_type) or fiscal_series(doc.company, doc.es_invoice_type)
	)


def fiscal_series(company: str, invoice_type: str) -> str:
	series = frappe.db.get_value(
		"ES Invoice Series",
		{"parent": company, "parenttype": "Company", "invoice_type": invoice_type},
		"series",
	)
	if not series:
		frappe.throw(
			_(
				"La compañía {0} numera al emitir pero no tiene serie para el tipo de factura {1}."
				" Añádala en la ficha de la compañía, pestaña «Spain Compliance», tabla «Series por"
				" tipo de factura» (p. ej. {2})."
			).format(frappe.bold(company), frappe.bold(invoice_type), "F-.ABBR.-.YY.-.#####"),
			title=_("Falta la serie"),
		)
	return series


def rename_to_fiscal_series(doc: Document, series: str) -> str:
	return rename_document(doc, make_autoname(series, doc=doc))


def rename_document(doc: Document, new_name: str) -> str:
	"""Renombra la factura durante el submit (del nombre del borrador al fiscal).

	rename_doc actualiza los hijos en la base de datos; los de memoria se re-enlazan
	para que el resto del submit no los guarde con el nombre viejo. `localname` hace
	que el formulario del navegador (también el del TPV) pase al nombre nuevo al
	recibir la respuesta: sin él seguiría con el borrador, que ya no existe, y al
	imprimir fallaría (frappe/desk/form/save.py → model/sync.js rename_after_save).

	El `list_update` sin nombre hace que las listas abiertas del doctype se recarguen
	enteras. El `list_update` normal del submit lleva solo el nombre nuevo: la lista
	lo añade y deja la fila del borrador, que solo quita si la consulta por nombres
	vuelve vacía (frappe list_view.js, process_document_refreshes)."""
	old_name = doc.name
	frappe.rename_doc(
		doctype=doc.doctype, old=old_name, new=new_name, force=True, show_alert=False, rebuild_search=False
	)
	doc.name = new_name
	doc.set_parent_in_children()
	doc.localname = old_name
	frappe.publish_realtime("list_update", {"doctype": doc.doctype}, doctype=doc.doctype, after_commit=True)
	return new_name
