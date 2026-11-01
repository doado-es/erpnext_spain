# Los módulos «Aeat» y «Nif» pasan a llamarse «ES Aeat» y «ES Nif» (carpetas
# es_aeat y es_nif), como el resto de módulos de la app. migrate crea los
# Module Def nuevos y la sincronización mueve los doctypes e informes; aquí se
# llevan al módulo nuevo los demás enlaces que queden y se borran los antiguos.

import frappe

RENAMED_MODULES = {"Aeat": "ES Aeat", "Nif": "ES Nif"}


def execute():
	for old, new in RENAMED_MODULES.items():
		if not frappe.db.exists("Module Def", old):
			continue
		if not frappe.db.exists("Module Def", new):
			# El módulo nuevo siempre existe tras migrate; si no, no se toca nada.
			continue
		for doctype, fieldname in module_links():
			frappe.db.set_value(doctype, {fieldname: old}, fieldname, new, update_modified=False)
		# Sin on_trash: no hay barras laterales del módulo antiguo y no debe
		# tocar modules.txt.
		frappe.delete_doc("Module Def", old, ignore_on_trash=True, force=True)


def module_links() -> list[tuple[str, str]]:
	"""Campos Link a Module Def de doctypes con tabla (estándar y personalizados)."""
	links = frappe.get_all(
		"DocField",
		filters={"fieldtype": "Link", "options": "Module Def", "parenttype": "DocType"},
		fields=["parent", "fieldname"],
	) + frappe.get_all(
		"Custom Field",
		filters={"fieldtype": "Link", "options": "Module Def"},
		fields=["dt as parent", "fieldname"],
	)
	result = []
	for link in links:
		meta = frappe.get_meta(link.parent)
		if meta.issingle or meta.is_virtual or link.parent == "Module Def":
			continue
		if not frappe.db.table_exists(link.parent):
			continue
		result.append((link.parent, link.fieldname))
	return sorted(set(result))
