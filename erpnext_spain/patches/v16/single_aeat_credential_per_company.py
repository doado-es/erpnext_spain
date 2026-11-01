# Revisión del 31/10/2026: un único certificado AEAT por empresa, compartido por
# VeriFactu, el SII y Facturae. Antes había una credencial por (empresa, propósito)
# y un campo de enlace por servicio en Company.
#
# Por empresa se conserva una credencial: la habilitada, con la vigencia más larga
# y, a igualdad, la de VeriFactu. Las demás se borran (las consultas a la AEAT que
# las citaban pasan a la conservada). La conservada se renombra a la compañía y se
# guarda de nuevo para extraer los PEM con el nombre nuevo.
#
# pre_model_sync: el doctype nuevo declara `company` única y la sincronización
# fallaría si quedaran dos credenciales de la misma empresa.

import os

import frappe

DOCTYPE = "ES AEAT Credential"
OBSOLETE_COMPANY_FIELDS = ("es_verifactu_credential", "es_sii_credential", "es_einvoice_credential")


def execute():
	if frappe.db.table_exists(DOCTYPE) and frappe.db.has_column(DOCTYPE, "purpose"):
		_merge_credentials()
	for fieldname in OBSOLETE_COMPANY_FIELDS:
		name = f"Company-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)


def _merge_credentials() -> None:
	from erpnext_spain.es_aeat.doctype.es_aeat_credential.es_aeat_credential import KEYS_DIR
	from erpnext_spain.es_aeat.utils import absolute_site_path

	table = frappe.qb.DocType(DOCTYPE)
	rows = (
		frappe.qb.from_(table)
		.select(table.name, table.company, table.purpose, table.enabled, table.valid_until)
		.run(as_dict=True)
	)
	by_company: dict[str, list] = {}
	for row in rows:
		by_company.setdefault(row.company, []).append(row)

	query = frappe.qb.DocType("ES Verifactu Aeat Query")
	for company, credentials in by_company.items():
		credentials.sort(
			key=lambda row: (
				not row.enabled,
				-(row.valid_until.toordinal() if row.valid_until else 0),
				row.purpose != "VeriFactu",
			)
		)
		keep, others = credentials[0], credentials[1:]
		if others:
			(
				frappe.qb.update(query)
				.set(query.credential, keep.name)
				.where(query.credential.isin([row.name for row in others]))
				.run()
			)
		for row in others:
			frappe.delete_doc(DOCTYPE, row.name, ignore_permissions=True, force=True)

		# PEM con el nombre antiguo (empresa-propósito).
		for row in credentials:
			base = f"{frappe.scrub(company)}-{frappe.scrub(row.purpose or '')}"
			for suffix in ("cert.pem", "key.pem"):
				path = absolute_site_path(*KEYS_DIR, f"{base}-{suffix}")
				if os.path.exists(path):
					os.remove(path)

		if keep.name != company:
			frappe.rename_doc(DOCTYPE, keep.name, company, force=True, show_alert=False)
		try:
			frappe.get_doc(DOCTYPE, company).save(ignore_permissions=True)
		except Exception:
			frappe.log_error(
				title=f"Certificado AEAT de {company}",
				message=frappe.get_traceback()
				+ "\nNo se pudieron extraer los PEM al unificar las credenciales:"
				" vuelva a guardar la credencial con el certificado y su contraseña.",
			)
