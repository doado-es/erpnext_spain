# «Intracomunitario» se divide en «Entrega intracomunitaria» (clientes y ventas) y
# «Adquisición intracomunitaria» (proveedores y compras), y los artículos reciben
# la fila de su plantilla para recargo, retención y adquisición intracomunitaria
# (es_impuestos/item_tax.py). Se reparte por el sentido de cada registro; la
# categoría antigua se borra si ya nada la usa.

import frappe

from erpnext_spain.es_impuestos.initial_data import (
	INTRA_EU_PURCHASES,
	INTRA_EU_SALES,
	OLD_INTRA_EU,
	ensure_global_records,
)
from erpnext_spain.es_impuestos.item_tax import mirror_existing

BY_DOCTYPE = {
	"Customer": INTRA_EU_SALES,
	"Supplier": INTRA_EU_PURCHASES,
	"Sales Taxes and Charges Template": INTRA_EU_SALES,
	"Purchase Taxes and Charges Template": INTRA_EU_PURCHASES,
	"Item Tax": INTRA_EU_PURCHASES,  # en un artículo solo tiene sentido la compra
}


def execute():
	ensure_global_records()
	for doctype, category in BY_DOCTYPE.items():
		table = frappe.qb.DocType(doctype)
		frappe.qb.update(table).set(table.tax_category, category).where(
			table.tax_category == OLD_INTRA_EU
		).run()

	rule = frappe.qb.DocType("Tax Rule")
	for tax_type, category in (("Sales", INTRA_EU_SALES), ("Purchase", INTRA_EU_PURCHASES)):
		frappe.qb.update(rule).set(rule.tax_category, category).where(
			(rule.tax_category == OLD_INTRA_EU) & (rule.tax_type == tax_type)
		).run()

	address = frappe.qb.DocType("Address")
	link = frappe.qb.DocType("Dynamic Link")
	suppliers = (
		frappe.qb.from_(link)
		.select(link.parent)
		.where((link.parenttype == "Address") & (link.link_doctype == "Supplier"))
	)
	frappe.qb.update(address).set(address.tax_category, INTRA_EU_PURCHASES).where(
		(address.tax_category == OLD_INTRA_EU) & address.name.isin(suppliers)
	).run()
	frappe.qb.update(address).set(address.tax_category, INTRA_EU_SALES).where(
		address.tax_category == OLD_INTRA_EU
	).run()

	mirror_existing()

	if frappe.db.exists("Tax Category", OLD_INTRA_EU):
		try:
			frappe.delete_doc("Tax Category", OLD_INTRA_EU, ignore_permissions=True)
		except frappe.LinkExistsError:
			pass  # documentos ya emitidos la citan: se conserva
