# Facturación masiva de albaranes de venta y de compra (spec 15, F1 y F2).
#
# Se usa el mapeo nativo de ERPNext (make_sales_invoice / make_purchase_invoice
# con target_doc) para que cada línea enlace a su albarán y el porcentaje
# facturado se actualice como en una factura manual.

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

BACKGROUND_FROM = 20
ROLES = ("Accounts User", "Accounts Manager", "System Manager")
GROUP_FIELDS = (
	"company",
	"customer",
	"currency",
	"selling_price_list",
	"taxes_and_charges",
	"customer_address",
)


def check_role(doctype: str) -> None:
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("No tiene permiso para facturar albaranes."), frappe.PermissionError)
	frappe.has_permission(doctype, "create", throw=True)


def as_list(value) -> list[str]:
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.startswith("[") else [value]
	return list(dict.fromkeys(value or []))


# --- F1: albaranes de venta --------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def invoice_delivery_notes(
	delivery_notes: list | str, group_by_period: bool = False, submit: bool = False
) -> dict:
	"""Crea una factura de venta por grupo de albaranes. Devuelve las facturas
	creadas y los albaranes descartados con el motivo (o el job encolado)."""
	check_role("Sales Invoice")
	names = as_list(delivery_notes)
	if len(names) > BACKGROUND_FROM:
		frappe.enqueue(
			"erpnext_spain.es_facturacion.bulk.run_delivery_notes",
			queue="long",
			timeout=3600,
			names=names,
			group_by_period=cint(group_by_period),
			submit=cint(submit),
			user=frappe.session.user,
		)
		return {"queued": True, "count": len(names)}
	return run_delivery_notes(names, cint(group_by_period), cint(submit))


def run_delivery_notes(
	names: list[str], group_by_period: int = 0, submit: int = 0, user: str | None = None
) -> dict:
	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

	groups: dict[tuple, list[str]] = {}
	skipped = []
	for name in names:
		note = frappe.db.get_value(
			"Delivery Note",
			name,
			["docstatus", "status", "is_return", "per_billed", "posting_date", *GROUP_FIELDS],
			as_dict=True,
		)
		reason = None
		if not note:
			reason = _("no existe")
		elif note.docstatus != 1:
			reason = _("no está validado")
		elif note.is_return:
			reason = _("es una devolución")
		elif note.status == "Closed":
			reason = _("está cerrado")
		elif flt(note.per_billed) >= 100:
			reason = _("ya está facturado")
		if reason:
			skipped.append({"name": name, "reason": reason})
			continue
		frappe.has_permission("Delivery Note", "read", doc=name, throw=True)
		key = tuple(note.get(field) for field in GROUP_FIELDS)
		if group_by_period:
			key += (getdate(note.posting_date).strftime("%Y-%m"),)
		groups.setdefault(key, []).append(name)

	invoices = []
	for notes in groups.values():
		invoice = None
		for note in sorted(notes):
			invoice = make_sales_invoice(note, target_doc=invoice)
		invoice.insert()
		if submit:
			invoice.submit()
		invoices.append(invoice.name)
	result = {"invoices": invoices, "skipped": skipped}
	notify(
		user,
		_("Facturación de albaranes: {0} facturas creadas, {1} albaranes descartados.").format(
			len(invoices), len(skipped)
		),
	)
	return result


# --- F2: albaranes de compra ----------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def invoice_purchase_receipts(
	purchase_receipts: list | str, bill_no: str, bill_date: str, submit: bool = False
) -> str:
	"""Registra la factura del proveedor que agrupa varios albaranes de compra."""
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

	check_role("Purchase Invoice")
	names = as_list(purchase_receipts)
	if not names:
		frappe.throw(_("Seleccione al menos un albarán de compra."))
	if not (bill_no or "").strip() or not bill_date:
		frappe.throw(_("Indique el número y la fecha de la factura del proveedor."))
	receipts = [
		frappe.db.get_value(
			"Purchase Receipt",
			name,
			["name", "supplier", "company", "currency", "docstatus", "is_return", "per_billed", "status"],
			as_dict=True,
		)
		for name in names
	]
	keys = {(r.supplier, r.company, r.currency) for r in receipts if r}
	if len(keys) != 1:
		frappe.throw(
			_(
				"Los albaranes deben ser del mismo proveedor, compañía y moneda: una factura del proveedor no puede agruparlos."
			),
			title=_("Albaranes de varios proveedores"),
		)
	for receipt in receipts:
		if (
			receipt.docstatus != 1
			or receipt.is_return
			or receipt.status == "Closed"
			or flt(receipt.per_billed) >= 100
		):
			frappe.throw(_("El albarán {0} no está pendiente de facturar.").format(frappe.bold(receipt.name)))
		frappe.has_permission("Purchase Receipt", "read", doc=receipt.name, throw=True)
	invoice = None
	for name in sorted(names):
		invoice = make_purchase_invoice(name, target_doc=invoice)
	invoice.bill_no = bill_no.strip()
	invoice.bill_date = bill_date
	invoice.insert()
	if cint(submit):
		invoice.submit()
	return invoice.name


def notify(user: str | None, subject: str) -> None:
	if not user:
		return
	frappe.get_doc(
		{"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": subject}
	).insert(ignore_permissions=True)
