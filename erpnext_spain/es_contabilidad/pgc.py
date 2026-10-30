# Aplicación del plan PGC a una compañía (spec 02).

from __future__ import annotations

import frappe

# Doctypes por compañía que enlazan cuentas y que unset_existing_data de ERPNext
# no borra (verificado en v16.51: el asistente de configuración crea para
# España el Item Tax Template «Spain Tax», que bloquea el borrado de la cuenta
# de IVA). Se crean de nuevo después con los datos iniciales (spec 09 §3).
EXTRA_COMPANY_DOCTYPES = ("Tax Rule", "Item Tax Template")


def clear_company_chart(company: str) -> None:
	"""Borra el plan de cuentas de una compañía sin movimientos y lo que lo enlaza.

	Usa unset_existing_data del importador de planes de ERPNext (vacía las
	cuentas por defecto de Company y borra cuentas, cuentas de terceros, de modos
	de pago, de retención y plantillas de impuestos de venta y compra), después
	de borrar lo que esa función no contempla."""
	from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
		unset_existing_data,
	)

	for doctype in EXTRA_COMPANY_DOCTYPES:
		for name in frappe.get_all(doctype, filters={"company": company}, pluck="name"):
			frappe.delete_doc(doctype, name, ignore_permissions=True)
	unset_existing_data(company)
