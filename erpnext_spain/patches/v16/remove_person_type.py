# El tipo de persona de Facturae sale del NIF español o del «Tipo de cliente» de
# ERPNext: se borra el campo propio es_person_type de Customer y Company. Los
# clientes marcados como persona física pasan a «Individual».

import frappe


def execute():
	if frappe.db.has_column("Customer", "es_person_type"):
		customer = frappe.qb.DocType("Customer")
		(
			frappe.qb.update(customer)
			.set(customer.customer_type, "Individual")
			.where(customer.es_person_type == "Física")
			.run()
		)
	for doctype in ("Customer", "Company"):
		name = f"{doctype}-es_person_type"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
		frappe.clear_cache(doctype=doctype)
