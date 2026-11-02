# Pestaña «AEAT» de las facturas (revisión del 31/10/2026).
#
# Reúne en una pestaña propia, con una sección por sistema, los datos de VeriFactu
# de la factura de venta y el historial de cada uno: registros VeriFactu,
# registros del SII y facturas electrónicas. El historial no se copia en la factura: se lee de sus doctypes al
# abrir el formulario (`onload`, que ya exige permiso de lectura de la factura) y
# `get_all` aplica los permisos del usuario sobre cada doctype.
#
# Una compañía sin VeriFactu, SII ni historial no ve la pestaña: se comporta
# como ERPNext estándar (R7).

from __future__ import annotations

import frappe
from frappe.model.document import Document

from erpnext_spain.utils.gating import active_billing_system, is_pgc_company

SALES_INVOICE = "Sales Invoice"
PURCHASE_INVOICE = "Purchase Invoice"
ONLOAD_KEY = "es_fiscal"

TAB = "es_fiscal_tab"
# Una sección por sistema, cada una con su lista (EmbeddedList en fiscal_tab.js):
# VeriFactu (sus campos y sus registros), SII y factura electrónica.
VERIFACTU_HISTORY = "es_verifactu_history"
SII_SECTION, SII_HISTORY = "es_sii_history_section", "es_sii_history"
EINVOICE_SECTION, EINVOICE_HISTORY = "es_einvoice_history_section", "es_einvoice_history"
# Primera versión de la pestaña (una sola lista); los borra el patch split_fiscal_tab.
OBSOLETE = ("es_fiscal_history_section", "es_fiscal_history")


def html(fieldname: str, insert_after: str) -> dict:
	return {"fieldname": fieldname, "fieldtype": "HTML", "insert_after": insert_after}


def section(fieldname: str, label: str, insert_after: str) -> dict:
	return {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": "Section Break",
		"insert_after": insert_after,
	}


CUSTOM_FIELDS = {
	# Antes de «Connections», la última pestaña estándar.
	SALES_INVOICE: [
		{
			"fieldname": TAB,
			"label": "AEAT",
			"fieldtype": "Tab Break",
			"insert_after": "is_discounted",
		},
		# es_verifactu_seccion y sus campos (es_verifactu/setup.py) van tras la pestaña.
		html(VERIFACTU_HISTORY, "es_verifactu_exempt_cause"),
		section(SII_SECTION, "SII", VERIFACTU_HISTORY),
		html(SII_HISTORY, SII_SECTION),
		# es_einvoice y es_einvoice_status (es_efactura/setup.py) van tras la sección.
		section(EINVOICE_SECTION, "Factura electrónica", SII_HISTORY),
		html(EINVOICE_HISTORY, "es_einvoice_status"),
	],
	PURCHASE_INVOICE: [
		{
			"fieldname": TAB,
			"label": "SII / Factura electrónica",
			"fieldtype": "Tab Break",
			"insert_after": "remarks",
		},
		section(SII_SECTION, "SII", TAB),
		html(SII_HISTORY, SII_SECTION),
		section(EINVOICE_SECTION, "Factura electrónica", SII_HISTORY),
		html(EINVOICE_HISTORY, "es_e_invoice"),
	],
}


def onload(doc: Document, method: str | None = None) -> None:
	"""Historial de la factura para la pestaña. Tres lecturas por índice al abrir
	el formulario, solo si la compañía usa VeriFactu o el SII o la factura tiene
	historial de factura electrónica."""
	if doc.is_new():
		return
	system = active_billing_system(doc.company)
	einvoice = doc.get("es_einvoice") if doc.doctype == SALES_INVOICE else doc.get("es_e_invoice")
	if not system and not einvoice and (not is_pgc_company(doc.company) or not _has_billing_records(doc)):
		return  # compañías sin VeriFactu, SII ni PGC: sin consultas (R7)
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
			"send_on",
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
