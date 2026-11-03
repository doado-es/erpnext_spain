# El certificado de la credencial AEAT tiene que estar en private/files (ya no se
# privatiza al guardar: se rechaza). Las credenciales anteriores pueden apuntar a
# /files/…: o el archivo sigue público, o la versión anterior lo privatizó y el
# campo se quedó con la URL vieja. Se dejan apuntando al archivo privado.

import os

import frappe

from erpnext_spain.es_aeat.doctype.es_aeat_credential.es_aeat_credential import DOCTYPE, PRIVATE_FILES


def execute():
	for name, cert_file in frappe.get_all(
		DOCTYPE,
		filters={"cert_file": ["not like", f"{PRIVATE_FILES}%"]},
		fields=["name", "cert_file"],
		as_list=True,
	):
		if cert_file:
			frappe.db.set_value(DOCTYPE, name, "cert_file", private_url(cert_file), update_modified=False)


def private_url(cert_file: str) -> str:
	"""URL privada del certificado; si el archivo sigue público, se privatiza."""
	private = PRIVATE_FILES + os.path.basename(cert_file)
	if frappe.db.exists("File", {"file_url": private}):
		return private
	file_name = frappe.db.get_value("File", {"file_url": cert_file})
	if not file_name:
		return cert_file  # sin archivo: la credencial pedirá subirlo de nuevo al guardar
	file_doc = frappe.get_doc("File", file_name)
	file_doc.is_private = 1
	file_doc.save(ignore_permissions=True)
	return file_doc.file_url
