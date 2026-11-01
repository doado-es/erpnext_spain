# El tipo de factura por defecto del perfil de TPV y del cliente se llamaba
# es_invoice_type, como el de la factura, y la limpieza de la desinstalación los
# tomaba por campos ajenos. Pasan a es_pos_invoice_type y es_default_invoice_type.

import frappe

RENAMES = {"POS Profile": "es_pos_invoice_type", "Customer": "es_default_invoice_type"}


def execute():
	for doctype, new in RENAMES.items():
		old = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": "es_invoice_type"})
		if not old:
			continue
		if frappe.db.has_column(doctype, new):
			for name, value in frappe.get_all(
				doctype,
				filters={"es_invoice_type": ["is", "set"]},
				fields=["name", "es_invoice_type"],
				as_list=True,
			):
				frappe.db.set_value(doctype, name, new, value, update_modified=False)
		frappe.delete_doc("Custom Field", old, ignore_permissions=True, force=True)
