# Revisión del 31/10/2026: un solo método de rectificación en Sales Invoice.
# `es_correction_method` (códigos Facturae) desaparece; Facturae deriva su código
# de `es_rectification_method` (02 por diferencias, 01 por sustitución).
# Los borradores con «01» pasan a «Por sustitución»; las facturas emitidas no se
# tocan (su Facturae ya está generada).

import frappe

FIELD = "Sales Invoice-es_correction_method"


def execute():
	if frappe.db.has_column("Sales Invoice", "es_correction_method"):
		invoice = frappe.qb.DocType("Sales Invoice")
		(
			frappe.qb.update(invoice)
			.set(invoice.es_rectification_method, "Por sustitución")
			.where((invoice.docstatus == 0) & (invoice.es_correction_method == "01"))
			.run()
		)
	if frappe.db.exists("Custom Field", FIELD):
		frappe.delete_doc("Custom Field", FIELD, ignore_permissions=True, force=True)
