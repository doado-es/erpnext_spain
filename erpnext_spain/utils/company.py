# Razón social de la compañía (es_legal_name, pestaña Spain Compliance).
#
# En ERPNext el nombre de la compañía suele ser corto («ctg»); la AEAT, Facturae
# y los ficheros bancarios necesitan la razón social, que se valida junto al NIF.
# Por defecto es el nombre de la compañía: se rellena al guardar si está vacía y
# `legal_name` cae al nombre si aún no se ha guardado.

from __future__ import annotations

import frappe
from frappe.model.document import Document

FIELD = "es_legal_name"


def legal_name(company: str | None) -> str:
	"""Razón social de la compañía o, si no tiene, su nombre."""
	if not company:
		return ""
	values = frappe.get_cached_value("Company", company, ["company_name", FIELD], as_dict=True)
	if not values:
		return ""
	return (values.get(FIELD) or "").strip() or values.company_name


def set_default_legal_name(doc: Document, method: str | None = None) -> None:
	"""doc_event validate de Company: razón social vacía → nombre de la compañía."""
	if not (doc.get(FIELD) or "").strip():
		doc.set(FIELD, doc.company_name)


def fill_missing_legal_names() -> None:
	"""Compañías existentes sin razón social: toman su nombre (after_migrate,
	idempotente; no pisa lo que haya escrito el usuario)."""
	if not frappe.db.has_column("Company", FIELD):
		return
	company = frappe.qb.DocType("Company")
	(
		frappe.qb.update(company)
		.set(company[FIELD], company.company_name)
		.where(company[FIELD].isnull() | (company[FIELD] == ""))
		.run()
	)
	for name in frappe.get_all("Company", pluck="name"):
		frappe.clear_document_cache("Company", name)
