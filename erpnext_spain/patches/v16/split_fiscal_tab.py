# Pestaña fiscal de las facturas: una sección por sistema (VeriFactu, SII, factura
# electrónica) en lugar de una sola lista de envíos. Se borran los campos de la
# primera versión.

import frappe

from erpnext_spain.es_facturacion.fiscal_tab import OBSOLETE


def execute():
	for doctype in ("Sales Invoice", "Purchase Invoice"):
		for fieldname in OBSOLETE:
			name = f"{doctype}-{fieldname}"
			if frappe.db.exists("Custom Field", name):
				frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
		frappe.clear_cache(doctype=doctype)
