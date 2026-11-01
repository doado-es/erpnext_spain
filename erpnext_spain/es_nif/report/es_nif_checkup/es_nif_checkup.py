# Copyright (c) 2026, ct.galega and contributors
# For license information, please see license.txt

# Report de higiene de datos pre-go-live (spec 14 §3): terceros y empresas
# con NIF ausente o inválido (patrón español). La validación se hace en
# Python con el validador puro — sin SQL crudo (doc 12 §19).

from __future__ import annotations

import frappe

from erpnext_spain.es_nif import validator

DEFECT_TYPES = {
	validator.FORMAT: "formato",
	validator.CONTROL_LETTER: "letra de control",
	validator.CONTROL_DIGIT: "dígito de control",
	validator.ORG_LETTER: "letra de organización",
}
MISSING_DEFECT = "ausente"

THIRD_PARTIES = (
	{"doctype": "Customer", "label": "Cliente", "name_field": "customer_name", "filter_disabled": True},
	{"doctype": "Supplier", "label": "Proveedor", "name_field": "supplier_name", "filter_disabled": True},
	{"doctype": "Company", "label": "Empresa", "name_field": "company_name", "filter_disabled": False},
)

MISSING_SUGGESTION = (
	"Añadir el NIF en la ficha del tercero: es obligatorio para activar VeriFactu y"
	" evitará rechazos AEAT por destinatario sin identificación."
)


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
	columns = [
		{"label": "Tipo de tercero", "fieldname": "party_type", "fieldtype": "Data", "width": 120},
		{"label": "ID", "fieldname": "identifier", "fieldtype": "Data", "width": 220},
		{"label": "Razón social", "fieldname": "legal_name", "fieldtype": "Data", "width": 300},
		{"label": "NIF", "fieldname": "tax_id", "fieldtype": "Data", "width": 130},
		{"label": "Defecto", "fieldname": "defect", "fieldtype": "Data", "width": 150},
		{"label": "Sugerencia", "fieldname": "suggestion", "fieldtype": "Data", "width": 460},
	]

	data: list[dict] = []
	for party in THIRD_PARTIES:
		for record in _parties(party):
			row = _evaluate(party, record)
			if row:
				data.append(row)

	return columns, data


def _parties(party: dict) -> list[frappe._dict]:
	filters = {"disabled": 0} if party["filter_disabled"] else None
	return frappe.get_all(
		party["doctype"],
		filters=filters,
		fields=["name", party["name_field"], "tax_id"],
		order_by="name asc",
	)


def _evaluate(party: dict, record: frappe._dict) -> dict | None:
	tax_id = (record.tax_id or "").strip()

	if not tax_id:
		return _row(party, record, MISSING_DEFECT, tax_id, MISSING_SUGGESTION)

	if not validator.looks_spanish(tax_id):
		return None

	try:
		validator.validate_spanish_tax_id(tax_id)
	except validator.InvalidTaxID as exc:
		defect = DEFECT_TYPES.get(exc.error_type, exc.error_type)
		return _row(party, record, defect, tax_id, str(exc))

	return None


def _row(party: dict, record: frappe._dict, defect: str, tax_id: str, suggestion: str) -> dict:
	return {
		"party_type": party["label"],
		"identifier": record.name,
		"legal_name": record.get(party["name_field"]),
		"tax_id": tax_id,
		"defect": defect,
		"suggestion": suggestion,
	}
