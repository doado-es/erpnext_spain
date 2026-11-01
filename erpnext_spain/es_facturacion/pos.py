# Ventas por TPV (POS): tipo de factura y serie.
#
# El tipo de factura decide la serie fiscal (mapeo tipo → serie de la compañía) y
# el TipoFactura de VeriFactu y del SII. En el TPV la venta habitual es una
# factura simplificada (F2) a un cliente de mostrador sin NIF; con el tipo por
# defecto de la factura (F1) la AEAT la rechaza por falta de destinatario.
#
# Tipo por defecto de una factura nueva (en este orden):
#   1. El del cliente («Tipo de factura por defecto»): p. ej. F1 para una empresa
#      que compra en el mostrador y pide factura completa. Un tipo simplificado del
#      cliente solo vale en ventas por TPV.
#   2. En ventas por TPV, el del perfil de TPV (F2 si no se indica otro).
#   3. Si no, el de la factura (F1).
# Las devoluciones de una simplificada son R5, con un motivo por defecto (el TPV
# no lo pide y es obligatorio).
#
# El perfil de TPV puede tener serie propia para su tipo de factura (una serie por
# caja); las devoluciones usan la serie R5 de la compañía.

import frappe
from frappe import _

from erpnext_spain.utils.gating import is_pgc_company

INVOICE_TYPE_FIELD = "es_invoice_type"
POS_TYPE_FIELD = "es_pos_invoice_type"
CUSTOMER_TYPE_FIELD = "es_default_invoice_type"
DEFAULT_TYPE = "F1"
POS_DEFAULT_TYPE = "F2"
SIMPLIFIED_RETURN_TYPE = "R5"
POS_RETURN_REASON = "Devolución en el punto de venta"


def is_simplified(invoice_type: str | None) -> bool:
	return bool(invoice_type) and bool(
		frappe.get_cached_value("ES Invoice Type", invoice_type, "is_simplified")
	)


def default_invoice_type(doc) -> str | None:
	"""Tipo de factura que corresponde a la venta, o None si no hay preferencia."""
	if doc.get("is_return"):
		original = doc.get("return_against") and frappe.db.get_value(
			"Sales Invoice", doc.return_against, INVOICE_TYPE_FIELD
		)
		return SIMPLIFIED_RETURN_TYPE if is_simplified(original) else None
	customer_type = doc.get("customer") and frappe.get_cached_value(
		"Customer", doc.customer, CUSTOMER_TYPE_FIELD
	)
	if customer_type and (doc.get("is_pos") or not is_simplified(customer_type)):
		return customer_type
	if doc.get("is_pos") and doc.get("pos_profile"):
		return frappe.get_cached_value("POS Profile", doc.pos_profile, POS_TYPE_FIELD) or POS_DEFAULT_TYPE
	return None


def set_invoice_type(doc, method=None) -> None:
	"""Sales Invoice.validate: tipo por defecto en las facturas nuevas."""
	if not doc.is_new() or doc.docstatus != 0 or not is_pgc_company(doc.company):
		return
	wanted = default_invoice_type(doc)
	current = doc.get(INVOICE_TYPE_FIELD)
	if wanted and (
		not current or current == DEFAULT_TYPE or (doc.get("is_return") and not current.startswith("R"))
	):
		doc.set(INVOICE_TYPE_FIELD, wanted)
	if doc.get("is_pos") and doc.get("is_return") and not (doc.get("es_rectification_reason") or "").strip():
		doc.es_rectification_reason = POS_RETURN_REASON


def pos_series(doc, invoice_type: str | None) -> str | None:
	"""Serie propia del perfil de TPV para su tipo de factura (o None)."""
	if not doc or not doc.get("is_pos") or not doc.get("pos_profile"):
		return None
	values = frappe.get_cached_value(
		"POS Profile", doc.pos_profile, [POS_TYPE_FIELD, "es_series"], as_dict=True
	)
	if values and values.es_series and (values.get(POS_TYPE_FIELD) or POS_DEFAULT_TYPE) == invoice_type:
		return values.es_series
	return None


def validate_pos_profile(doc, method=None) -> None:
	"""POS Profile.validate: la serie propia no puede numerar otro tipo de factura."""
	series = (doc.get("es_series") or "").strip()
	if not series or not is_pgc_company(doc.company):
		return
	invoice_type = doc.get(POS_TYPE_FIELD) or POS_DEFAULT_TYPE
	other_type = frappe.db.get_value(
		"ES Invoice Series",
		{
			"parent": doc.company,
			"parenttype": "Company",
			"series": series,
			"invoice_type": ["!=", invoice_type],
		},
		"invoice_type",
	)
	if other_type:
		frappe.throw(
			_(
				"La serie {0} ya es la del tipo {1} en la compañía: cada serie numera un solo tipo de factura."
			).format(frappe.bold(series), frappe.bold(other_type))
		)
