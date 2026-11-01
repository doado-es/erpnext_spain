# Efectos pendientes de cobro o de pago para las remesas (adeudos SEPA y confirming).
#
# Un efecto es un vencimiento de la factura (fila de Payment Schedule) con su
# importe pendiente. Si la factura no tiene vencimientos, la factura entera es
# un efecto con su fecha de vencimiento.
#
# El pendiente de cada vencimiento no siempre está al día: ERPNext solo lo
# actualiza cuando el pago indica el vencimiento (payment_term). Por eso el
# pendiente de la factura manda: lo que falte para cuadrar se descuenta de los
# vencimientos más antiguos, que son los que se pagan primero.

import frappe
from frappe.utils import flt, getdate

ROUNDING = 0.005


def pending_effects(
	invoice_doctype: str,
	party_field: str,
	company: str,
	invoice_fields: list[str],
	parties: list[str] | None = None,
	payment_terms_templates: list[str] | None = None,
	include_returns: bool = False,
) -> list[dict]:
	"""Efectos de las facturas validadas con pendiente de la compañía.

	Cada efecto lleva los campos pedidos de la factura más `invoice`,
	`payment_term`, `due_date`, `mode_of_payment` y `amount`. Los abonos
	(pendiente negativo) solo se incluyen con `include_returns`, como un único
	efecto."""
	filters = {"company": company, "docstatus": 1, "outstanding_amount": ["!=", 0]}
	if parties:
		filters[party_field] = ["in", parties]
	if payment_terms_templates:
		filters["payment_terms_template"] = ["in", payment_terms_templates]
	fields = list(
		dict.fromkeys(["name", party_field, "due_date", "outstanding_amount", "is_return", *invoice_fields])
	)
	invoices = frappe.get_all(invoice_doctype, filters=filters, fields=fields, order_by="due_date, name")
	invoices = [
		i
		for i in invoices
		if (flt(i.outstanding_amount) > 0 and not i.is_return)
		or (include_returns and flt(i.outstanding_amount) < 0)
	]
	if not invoices:
		return []

	schedules: dict[str, list] = {}
	for row in frappe.get_all(
		"Payment Schedule",
		filters={"parenttype": invoice_doctype, "parent": ["in", [i.name for i in invoices]]},
		fields=["parent", "payment_term", "due_date", "mode_of_payment", "payment_amount", "outstanding"],
		order_by="parent, due_date, idx",
	):
		schedules.setdefault(row.parent, []).append(row)

	effects = []
	for invoice in invoices:
		base = {field: invoice.get(field) for field in fields if field not in ("name", "outstanding_amount")}
		rows = schedules.get(invoice.name) if flt(invoice.outstanding_amount) > 0 else None
		if not rows:
			effects.append(
				{
					**base,
					"invoice": invoice.name,
					"payment_term": None,
					"due_date": invoice.due_date,
					"mode_of_payment": None,
					"amount": flt(invoice.outstanding_amount),
				}
			)
			continue
		for row, amount in zip(rows, split_outstanding(rows, flt(invoice.outstanding_amount)), strict=True):
			if amount > ROUNDING:
				effects.append(
					{
						**base,
						"invoice": invoice.name,
						"payment_term": row.payment_term,
						"due_date": row.due_date,
						"mode_of_payment": row.mode_of_payment,
						"amount": amount,
					}
				)
	return effects


def split_outstanding(rows: list, outstanding: float) -> list[float]:
	"""Pendiente de cada vencimiento, cuadrado con el pendiente de la factura."""
	amounts = [flt(row.outstanding) if row.payment_term else flt(row.payment_amount) for row in rows]
	excess = sum(amounts) - outstanding
	for index, amount in enumerate(amounts):
		if excess <= ROUNDING:
			break
		taken = min(amount, excess)
		amounts[index] = flt(amount - taken, 2)
		excess -= taken
	return amounts


def subtract_reserved(effects: list[dict], reserved: dict[tuple, float]) -> list[dict]:
	"""Descuenta lo que ya está en otras remesas en curso: clave (factura, vencimiento)."""
	result = []
	for effect in effects:
		amount = flt(effect["amount"]) - flt(reserved.get((effect["invoice"], effect["payment_term"] or "")))
		if abs(amount) > ROUNDING and (amount > 0) == (flt(effect["amount"]) > 0):
			result.append({**effect, "amount": flt(amount, 2)})
	return result


def in_range(
	effects: list[dict],
	from_due_date: str | None = None,
	to_due_date: str | None = None,
	min_amount: float | None = None,
	max_amount: float | None = None,
) -> list[dict]:
	"""Filtro por vencimiento e importe (en valor absoluto: los abonos también entran)."""
	return [
		e
		for e in effects
		if (not from_due_date or getdate(e["due_date"]) >= getdate(from_due_date))
		and (not to_due_date or getdate(e["due_date"]) <= getdate(to_due_date))
		and (not flt(min_amount) or abs(flt(e["amount"])) >= flt(min_amount))
		and (not flt(max_amount) or abs(flt(e["amount"])) <= flt(max_amount))
	]


def as_list(value) -> list[str]:
	"""Lista desde un argumento de whitelist (lista, JSON o texto separado por comas)."""
	if not value:
		return []
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.strip().startswith("[") else value.split(",")
	return [v.strip() for v in value if v and v.strip()]
