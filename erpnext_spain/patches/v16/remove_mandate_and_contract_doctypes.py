# Revisión del 31/10/2026: el mandato SEPA pasa a la cuenta bancaria del
# cliente y el contrato de confirming a las normas de la cuenta de la compañía.
# Se borran los doctypes de la primera versión y sus tablas.

import frappe


def execute():
	for doctype in ("ES Sepa Mandate", "ES Confirming Contract"):
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True)
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
