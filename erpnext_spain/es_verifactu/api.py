# Endpoint whitelisted del form de Company (spec 04 §2.1/§15): estado VeriFactu
# de la empresa para la UX — nº de registros pendientes de envío (aviso de
# desactivación) y congelación de la fecha de activación (read-only dinámico).
#
# Permisos explícitos al inicio (doc 12 §18): acceso de lectura sobre la
# Company de la que se pregunta — no basta la protección estándar de
# @frappe.whitelist. No dispara comunicación con la AEAT: es solo lectura del
# libro local.

from __future__ import annotations

import frappe

from erpnext_spain.es_verifactu.doctype.es_verifactu_billing_record.es_verifactu_billing_record import (
	has_records,
	pending_send_count,
)


@frappe.whitelist()
def verifactu_status(company: str) -> dict[str, int | bool]:
	"""Estado del libro VeriFactu de la empresa.

	:param company: nombre de la Company.
	:return: ``pending`` (nº de registros PendienteEnvio del outbox) y
		``frozen`` (la empresa ya tiene registros → fecha de activación
		congelada).
	"""
	if not frappe.has_permission("Company", "read", doc=company):
		frappe.throw(
			f"No tiene permiso de lectura sobre la empresa {company}. Remedio:"
			" solicite el acceso pertinente al administrador del site.",
			frappe.PermissionError,
		)

	return {
		"pending": pending_send_count(company),
		"frozen": has_records(company),
	}
