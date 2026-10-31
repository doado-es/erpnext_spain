# Pestaña «VeriFactu / SII» de las facturas (revisión del 31/10/2026).
#
# Reúne en una pestaña propia los datos de VeriFactu de la factura de venta y el
# historial de envíos: registros VeriFactu, registros del SII y facturas
# electrónicas. El historial no se copia en la factura: se lee de sus doctypes al
# abrir el formulario (`onload`, que ya exige permiso de lectura de la factura) y
# `get_all` aplica los permisos del usuario sobre cada doctype.
#
# Una compañía sin VeriFactu, SII ni historial no ve la pestaña: se comporta
# como ERPNext estándar (R7).

from __future__ import annotations

import frappe
from frappe.model.document import Document

from erpnext_spain.utils.gating import active_billing_system

SALES_INVOICE = "Sales Invoice"
PURCHASE_INVOICE = "Purchase Invoice"
ONLOAD_KEY = "es_fiscal"

TAB = "es_fiscal_tab"
HISTORY_SECTION = "es_fiscal_history_section"
HISTORY = "es_fiscal_history"


def tab_fields(label: str, insert_after: str) -> list[dict]:
	return [
		{"fieldname": TAB, "label": label, "fieldtype": "Tab Break", "insert_after": insert_after},
		{
			"fieldname": HISTORY_SECTION,
			"label": "Historial de envíos",
			"fieldtype": "Section Break",
			# Tras la sección VeriFactu en ventas; en compras, al principio de la pestaña.
			"insert_after": "es_verifactu_exempt_cause" if label.startswith("VeriFactu") else TAB,
		},
		{
			"fieldname": HISTORY,
			"label": "Historial de envíos",
			"fieldtype": "HTML",
			# Debajo de los enlaces a la factura electrónica (es_efactura/setup.py).
			"insert_after": "es_einvoice_status" if label.startswith("VeriFactu") else "es_e_invoice",
		},
	]


CUSTOM_FIELDS = {
	# Antes de «Connections», la última pestaña estándar.
	SALES_INVOICE: tab_fields("VeriFactu / SII", "is_discounted"),
	PURCHASE_INVOICE: tab_fields("SII / Factura electrónica", "remarks"),
}


def onload(doc: Document, method: str | None = None) -> None:
	"""Historial de la factura para la pestaña. Tres lecturas por índice al abrir
	el formulario, solo si la compañía usa VeriFactu o el SII o la factura tiene
	historial de factura electrónica."""
	if doc.is_new():
		return
	system = active_billing_system(doc.company)
	einvoice = doc.get("es_einvoice") if doc.doctype == SALES_INVOICE else doc.get("es_e_invoice")
	if not system and not einvoice and not _has_billing_records(doc):
		return
	doc.set_onload(ONLOAD_KEY, {"system": system, **history(doc.doctype, doc.name)})


def _has_billing_records(doc: Document) -> bool:
	"""Registros de una compañía que ya desactivó VeriFactu o el SII (el historial
	se sigue viendo)."""
	if doc.doctype == SALES_INVOICE and frappe.db.exists(
		"ES Verifactu Billing Record", {"sales_invoice": doc.name}
	):
		return True
	return bool(frappe.db.exists("ES Sii Record", {"voucher_type": doc.doctype, "voucher_no": doc.name}))


def history(doctype: str, name: str) -> dict[str, list]:
	verifactu = []
	if doctype == SALES_INVOICE:
		verifactu = frappe.get_all(
			"ES Verifactu Billing Record",
			filters={"sales_invoice": name},
			fields=["name", "record_type", "status", "creation", "response_error_code", "response_error_msg"],
			order_by="creation asc",
		)
	sii = frappe.get_all(
		"ES Sii Record",
		filters={"voucher_type": doctype, "voucher_no": name},
		fields=[
			"name",
			"communication",
			"status",
			"deadline",
			"last_attempt",
			"csv",
			"error_code",
			"error_description",
		],
		order_by="creation asc",
	)
	link = "sales_invoice" if doctype == SALES_INVOICE else "purchase_invoice"
	einvoices = frappe.get_all(
		"ES E-Invoice",
		filters={link: name},
		fields=["name", "format", "channel", "status", "modified", "face_registry_number"],
		order_by="creation asc",
	)
	return {"verifactu": verifactu, "sii": sii, "einvoice": einvoices}
