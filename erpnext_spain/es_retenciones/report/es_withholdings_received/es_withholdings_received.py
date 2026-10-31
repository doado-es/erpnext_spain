# Retenciones soportadas (spec 08 §6): lo que nos retienen los clientes, para el
# modelo 130 y para cuadrar con sus certificados.
#
# Fuente: filas de impuestos de facturas de venta validadas clasificadas como
# «Retención IRPF» (tipo negativo, cuenta 473; spec 03 y 08 §4). Cuando exista el
# Registro Fiscal IVA (spec 06), pasará a leerse de él.

import frappe
from frappe import _

from erpnext_spain.es_impuestos.codes import TAX_TYPES


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Elija la compañía."))
	return get_columns(), get_data(filters)


def get_columns() -> list[dict]:
	return [
		{
			"fieldname": "customer",
			"label": _("Cliente"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 180,
		},
		{"fieldname": "customer_name", "label": _("Nombre"), "fieldtype": "Data", "width": 200},
		{"fieldname": "tax_id", "label": _("NIF"), "fieldtype": "Data", "width": 110},
		{"fieldname": "rate", "label": _("Tipo (%)"), "fieldtype": "Percent", "width": 80},
		{"fieldname": "invoices", "label": _("Facturas"), "fieldtype": "Int", "width": 80},
		{
			"fieldname": "taxable_amount",
			"label": _("Base de retención"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{"fieldname": "withholding_amount", "label": _("Retención"), "fieldtype": "Currency", "width": 120},
	]


def get_data(filters) -> list[dict]:
	invoice = frappe.qb.DocType("Sales Invoice")
	tax = frappe.qb.DocType("Sales Taxes and Charges")
	query = (
		frappe.qb.from_(tax)
		.join(invoice)
		.on(invoice.name == tax.parent)
		.select(
			invoice.customer,
			invoice.customer_name,
			invoice.tax_id,
			tax.rate,
			tax.parent,
			tax.base_tax_amount,
		)
		.where(tax.parenttype == "Sales Invoice")
		.where(tax.es_tax_type == TAX_TYPES["IRPF"])
		.where(invoice.docstatus == 1)
		.where(invoice.company == filters.company)
	)
	if filters.get("from_date"):
		query = query.where(invoice.posting_date >= filters.from_date)
	if filters.get("to_date"):
		query = query.where(invoice.posting_date <= filters.to_date)
	if filters.get("customer"):
		query = query.where(invoice.customer == filters.customer)

	grouped: dict[tuple, dict] = {}
	for row in query.run(as_dict=True):
		key = (row.customer, row.tax_id, abs(row.rate or 0))
		data = grouped.setdefault(
			key,
			frappe._dict(
				customer=row.customer,
				customer_name=row.customer_name,
				tax_id=row.tax_id,
				rate=abs(row.rate or 0),
				invoices=set(),
				taxable_amount=0.0,
				withholding_amount=0.0,
			),
		)
		data.invoices.add(row.parent)
		withheld = -(row.base_tax_amount or 0)
		data.withholding_amount += withheld
		if row.rate:
			data.taxable_amount += withheld * 100 / abs(row.rate)
	rows = sorted(grouped.values(), key=lambda r: (r.customer or "", r.rate))
	for row in rows:
		row.invoices = len(row.invoices)
	return rows
