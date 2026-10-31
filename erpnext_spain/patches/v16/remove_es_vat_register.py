# El Registro Fiscal IVA (ES Vat Register) se sustituye por el cálculo sobre la
# marcha desde la factura (es_iva/rows.py, revisión del 31/10/2026): se borra
# el doctype y sus filas de los sitios donde llegó a instalarse.

import frappe


def execute():
	if frappe.db.exists("DocType", "ES Vat Register"):
		frappe.delete_doc("DocType", "ES Vat Register", force=True, ignore_missing=True)
	# delete_doc no borra la tabla de un doctype estándar.
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabES Vat Register`")
