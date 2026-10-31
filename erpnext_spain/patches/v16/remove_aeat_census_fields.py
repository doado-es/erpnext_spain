# Revisión del 31/10/2026: el contraste de NIF con la AEAT se hace a demanda desde
# la marca junto al NIF y no se guarda. Se borran los campos que lo almacenaban.

import frappe

FIELDS = ("es_aeat_status", "es_aeat_census_name", "es_aeat_result", "es_aeat_source", "es_aeat_checked_on")


def execute():
	for doctype in ("Customer", "Supplier"):
		for fieldname in FIELDS:
			name = f"{doctype}-{fieldname}"
			if frappe.db.exists("Custom Field", name):
				frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
		frappe.clear_cache(doctype=doctype)
