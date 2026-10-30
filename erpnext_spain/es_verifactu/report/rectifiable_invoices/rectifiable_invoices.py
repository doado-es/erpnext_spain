# Report Script «Rectifiable Invoices» — lote 5b (spec 04 §9): facturas
# cuyo último registro del libro fue marcado «Subsanable» por la estrategia
# de errores (rechazo AEAT que exige corrección humana). ORM puro (doc 12
# §19: sin SQL crudo), etiquetas en español, orden por cadena del SIF (el
# más antiguo primero — es también el orden de subsanación cuando la
# compañía exige «subsanación en orden»).

from __future__ import annotations

import frappe

LEDGER_DOCTYPE = "ES Verifactu Billing Record"
INVOICE_DOCTYPE = "Sales Invoice"


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	columns = [
		{"label": "Factura", "fieldname": "invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 220},
		{"label": "Compañía", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 200},
		{"label": "Fecha", "fieldname": "date", "fieldtype": "Date", "width": 100},
		{"label": "Tipo", "fieldname": "type", "fieldtype": "Data", "width": 60},
		{"label": "Código de error AEAT", "fieldname": "error_code", "fieldtype": "Data", "width": 150},
		{"label": "Descripción del error AEAT", "fieldname": "error_description", "fieldtype": "Small Text", "width": 400},
		{"label": "Pendiente desde", "fieldname": "pending_since", "fieldtype": "Datetime", "width": 160},
	]

	records = frappe.get_all(
		LEDGER_DOCTYPE,
		filters=_record_filters(filters),
		fields=[
			"name",
			"company",
			"sales_invoice",
			"invoice_type",
			"chain_index",
			"response_error_code",
			"response_error_msg",
			"modified",
		],
		order_by="company asc, chain_index asc",
	)

	invoices = _invoices({r.sales_invoice for r in records if r.sales_invoice})

	data = []
	for record in records:
		invoice = invoices.get(record.sales_invoice, frappe._dict())
		data.append(
			{
				"invoice": record.sales_invoice,
				"company": record.company,
				"date": invoice.posting_date,
				"type": record.invoice_type or invoice.es_invoice_type,
				"error_code": record.response_error_code,
				"error_description": record.response_error_msg,
				"pending_since": record.modified,
			}
		)

	return columns, data


def _record_filters(filters: dict | None) -> dict:
	"""Registros subsanables (la cura PENDIENTE: rectify() limpia el flag
	al regenerar), opcionalmente por compañía del filtro del report."""
	flt: dict = {"curable": 1}
	if filters and filters.get("company"):
		flt["company"] = filters["company"]
	return flt


def _invoices(names: set[str]) -> dict[str, frappe._dict]:
	if not names:
		return {}
	rows = frappe.get_all(
		INVOICE_DOCTYPE,
		filters={"name": ("in", list(names))},
		fields=["name", "posting_date", "es_invoice_type"],
	)
	return {row.name: row for row in rows}
