# Borrador de liquidación de IVA (spec 06 §5). No es el modelo 303.

from frappe import _

from erpnext_spain.es_iva.books import check_filters, return_draft


def execute(filters: dict | None = None):
	filters = check_filters(filters)
	columns = [
		{"fieldname": "concept", "label": _("Concepto"), "fieldtype": "Data", "width": 320},
		{"fieldname": "taxable_base", "label": _("Base imponible"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "tax_amount", "label": _("Cuota"), "fieldtype": "Currency", "width": 140},
	]
	return columns, return_draft(filters)
