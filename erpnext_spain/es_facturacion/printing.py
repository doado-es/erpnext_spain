# Datos de impuestos para el formato de factura (spec 05 §5).
#
# El desglose sale de la clasificación fiscal de las filas (spec 03) y del
# detalle por artículo que guarda ERPNext (`item_wise_tax_details`, v16), no de
# la descripción de la fila. Lo usa el formato de impresión y servirá de base al
# desglose de VeriFactu y al Registro Fiscal IVA (spec 06).

from collections import OrderedDict

import frappe
from frappe.utils import flt

from erpnext_spain.es_impuestos.codes import TAX_TYPES

# Menciones obligatorias según la calificación (RD 1619/2012, art. 6.1.j y m).
MENTIONS = {
	"S2": "Inversión del sujeto pasivo (art. 84.Uno.2º de la Ley 37/1992 del IVA).",
	"N1": "Operación no sujeta al IVA (arts. 7 y 14 de la Ley 37/1992).",
	"N2": "Operación no sujeta al IVA por las reglas de localización (arts. 68 a 70 de la Ley 37/1992).",
	"E1": "Operación exenta de IVA (art. 20 de la Ley 37/1992).",
	"E2": "Exportación exenta de IVA (art. 21 de la Ley 37/1992).",
	"E3": "Operación exenta de IVA (art. 22 de la Ley 37/1992).",
	"E4": "Operación exenta de IVA (arts. 23 y 24 de la Ley 37/1992).",
	"E5": "Entrega intracomunitaria exenta de IVA (art. 25 de la Ley 37/1992).",
	"E6": "Operación exenta de IVA.",
}


def tax_summary(doc) -> dict:
	"""Desglose de la factura por tipo de impuesto, tipo y calificación.

	Devuelve {"vat": [...], "withholding": [...], "mentions": [...]} con importes
	numéricos en la moneda de la factura (filas: tax_type, rate, base, amount,
	classification)."""
	rows_by_name = {row.name: row for row in doc.get("taxes") or []}
	groups: OrderedDict = OrderedDict()
	details = doc.get("item_wise_tax_details") or []

	if details:
		for detail in details:
			row = rows_by_name.get(detail.tax_row)
			if row:
				add(groups, row, flt(detail.rate), flt(detail.taxable_amount), flt(detail.amount))
	else:
		for row in rows_by_name.values():
			amount = flt(row.tax_amount)
			base = amount * 100 / flt(row.rate) if flt(row.rate) else flt(doc.net_total)
			add(groups, row, flt(row.rate), base, amount)

	vat = [g for g in groups.values() if g["tax_type"] != TAX_TYPES["IRPF"]]
	withholding = [g for g in groups.values() if g["tax_type"] == TAX_TYPES["IRPF"]]
	mentions = []
	for group in vat:
		mention = MENTIONS.get(group["classification"])
		if mention and mention not in mentions:
			mentions.append(mention)
	return {"vat": vat, "withholding": withholding, "mentions": mentions}


def add(groups: OrderedDict, row, rate: float, base: float, amount: float) -> None:
	tax_type = row.get("es_tax_type") or (row.description or "").strip()
	classification = row.get("es_vat_classification") or ""
	key = (tax_type, abs(rate), classification)
	group = groups.setdefault(
		key,
		{
			"tax_type": tax_type,
			"rate": abs(rate),
			"base": 0.0,
			"amount": 0.0,
			"classification": classification,
		},
	)
	group["base"] += base
	group["amount"] += amount


def get_es_tax_summary(doc) -> dict:
	"""Método Jinja: el desglose con los importes ya formateados."""
	summary = tax_summary(doc)
	currency = doc.get("currency")
	for key in ("vat", "withholding"):
		for row in summary[key]:
			row["base_formatted"] = frappe.utils.fmt_money(row["base"], currency=currency)
			row["amount_formatted"] = frappe.utils.fmt_money(row["amount"], currency=currency)
			row["rate_formatted"] = f"{row['rate']:g} %".replace(".", ",")
	return summary


def get_es_rectified_reference(doc) -> dict | None:
	"""Método Jinja: datos de la factura rectificada para el formato."""
	if doc.get("return_against"):
		date = frappe.db.get_value("Sales Invoice", doc.return_against, "posting_date")
		return {"number": doc.return_against, "date": frappe.utils.formatdate(date)}
	if doc.get("es_external_rectified_number"):
		return {
			"number": doc.es_external_rectified_number,
			"date": frappe.utils.formatdate(doc.get("es_external_rectified_date")),
		}
	return None
