# Modelo 180: resumen anual de retenciones sobre arrendamientos de inmuebles urbanos
# (el anual del 115). Diseño de registro del 180 (Orden HAP/1732/2014, actualizada por
# HFP/1284/2023): registros de 500 posiciones.

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_spain.es_modelos import informative as inf
from erpnext_spain.es_modelos.returns import ANNUAL, box, period_dates, set_box
from erpnext_spain.es_retenciones.codes import SITUATION_180

PERIODS = ANNUAL
LABELS = {
	"PER": "Número total de perceptores",
	"BAS": "Base de las retenciones e ingresos a cuenta",
	"RET": "Retenciones e ingresos a cuenta",
}


def compute(doc) -> tuple[dict, list[dict]]:
	start, end = period_dates(doc.fiscal_year, "0A")
	entries = inf.withholding_entries(doc.company, start, end, "115")
	properties = property_of(entries)
	grouped: dict[tuple, dict] = {}
	for entry in entries:
		key = (entry.party_type, entry.party, properties.get(entry.taxable_name))
		line = grouped.setdefault(
			key,
			{
				"party_type": entry.party_type,
				"party": entry.party,
				"tax_id": entry.tax_id or frappe.get_cached_value(entry.party_type, entry.party, "tax_id"),
				"party_name": party_name(entry.party_type, entry.party),
				"province_code": inf.province_code(entry.party_type, entry.party),
				"property": key[2],
				"amount": 0.0,
				"withheld": 0.0,
				"rate": 0.0,
				"last_date": None,
			},
		)
		line["amount"] += flt(entry.taxable_amount)
		line["withheld"] += flt(entry.withholding_amount)
		# Con varios tipos en el año, el último.
		if not line["last_date"] or entry.withholding_date >= line["last_date"]:
			line["rate"], line["last_date"] = flt(entry.tax_rate), entry.withholding_date
	lines = []
	for line in grouped.values():
		line.pop("last_date")
		line["amount"], line["withheld"] = round(line["amount"], 2), round(line["withheld"], 2)
		if not line["property"]:
			line["note"] = _("Factura sin inmueble arrendado: indíquelo en la factura de compra.")
		lines.append(line)
	return {}, lines


def property_of(entries) -> dict[str, str]:
	invoices = {e.taxable_name for e in entries if e.taxable_doctype == "Purchase Invoice"}
	if not invoices:
		return {}
	return dict(
		frappe.get_all(
			"Purchase Invoice",
			filters={"name": ["in", list(invoices)]},
			fields=["name", "es_leased_property"],
			as_list=True,
		)
	)


def party_name(party_type: str, party: str) -> str:
	field = "supplier_name" if party_type == "Supplier" else "customer_name"
	return frappe.get_cached_value(party_type, party, field) or party


def totals(doc) -> None:
	set_box(doc, "PER", len(doc.lines))
	set_box(doc, "BAS", sum(flt(line.amount) for line in doc.lines))
	set_box(doc, "RET", sum(flt(line.withheld) for line in doc.lines))
	doc.result = box(doc, "RET")


def build(doc) -> str:
	header = inf.record(
		[
			*inf.declarant_record(doc, "180"),
			(136, inf.num(box(doc, "PER"), 9)),
			(145, inf.signed_cents(box(doc, "BAS"), 16)),
			(161, inf.cents(box(doc, "RET"), 15)),
		]
	)
	return inf.as_file([header, *[perceptor(doc, line) for line in doc.lines]])


def perceptor(doc, line) -> str:
	prop = frappe.get_cached_doc("ES Leased Property", line.property) if line.property else None
	if not prop:
		frappe.throw(_("Fila {0}: falta el inmueble arrendado de {1}.").format(line.idx, line.party_name))
	situation = SITUATION_180.get((prop.situation or "")[:1])
	if not situation:
		frappe.throw(
			_("Fila {0}: el inmueble {1} está en el extranjero; no va en el modelo 180.").format(
				line.idx, prop.name
			)
		)
	street = inf.an(prop.address, 90)
	postal_code = "".join(c for c in (prop.postal_code or "") if c.isdigit())[:5]
	return inf.record(
		[
			*inf.declarant_head(doc, "180", "2"),
			(18, inf.nif(line.tax_id)),
			(36, inf.an(line.party_name, 40)),
			(76, inf.num(line.province_code or 0, 2)),
			(78, "1"),
			(79, inf.signed_cents(line.amount, 14)),
			(93, inf.cents(line.rate, 4)),
			(97, inf.cents(line.withheld, 13)),
			(110, inf.num(line.accrual_year or 0, 4)),
			(114, situation),
			(115, inf.an(prop.cadastral_reference, 20)),
			(140, street[:50]),
			(216, street[50:90].ljust(40)),
			(286, inf.an(prop.municipality, 30)),
			(321, postal_code[:2].rjust(2, "0") if postal_code else "  "),
			(323, postal_code.rjust(5, "0") if postal_code else "     "),
		]
	)
