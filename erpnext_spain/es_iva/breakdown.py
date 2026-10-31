# Desglose fiscal de una factura a partir de su clasificación (spec 06 §2 y §6).
#
# Función pura (solo lee el documento y cachés): la usan el Registro Fiscal IVA,
# que la persiste, el adaptador de VeriFactu (en lugar del stub que leía la
# descripción) y el SII. Así no depende del orden de los on_submit.
#
# - Base y cuota por artículo desde la tabla nativa de v16 `item_wise_tax_details`
#   (taxable_amount y amount, en moneda de la compañía) [verificado v16].
# - Agrupación por fila de impuesto y, dentro de ella, por calificación, tipo de
#   operación y tipo impositivo. La clasificación del Item Tax Template del
#   artículo manda sobre la de la fila (spec 03).
# - Rectificativas: los importes llegan ya en negativo.

from collections import OrderedDict

import frappe
from frappe.utils import flt

from erpnext_spain.es_impuestos.codes import TAX_TYPES

VAT = TAX_TYPES["IVA"]
SURCHARGE = TAX_TYPES["RE"]
WITHHOLDING = TAX_TYPES["IRPF"]
ROW_FIELDS = (
	"es_tax_type",
	"es_vat_classification",
	"es_operation_type",
	"es_regime_key",
	"es_withholding_key",
	"es_deductibility",
	"es_self_assessed",
)


def vat_breakdown(doc) -> list[dict]:
	"""Filas del desglose de la factura.

	Cada fila: tax_row, account, tax_type, vat_classification, operation_type,
	regime_key, withholding_key, deductibility, self_assessed, tax_rate,
	taxable_base, tax_amount (moneda de la compañía) y unclassified."""
	taxes = {row.name: row for row in doc.get("taxes") or []}
	if not taxes:
		return []
	item_overrides = item_tax_template_classification(doc)
	conversion = flt(doc.get("conversion_rate")) or 1
	groups: OrderedDict = OrderedDict()

	details = doc.get("item_wise_tax_details") or []
	if details:
		# Tipo de cada fila de impuesto: el suyo o, si es de importe fijo, el que
		# resulta de su base y su cuota totales (no de cada artículo: el reparto
		# redondea por línea).
		totals: dict[str, list[float]] = {}
		for detail in details:
			total = totals.setdefault(detail.tax_row, [0.0, 0.0, 0.0])
			total[0] = total[0] or flt(detail.rate)
			total[1] += flt(detail.taxable_amount)
			total[2] += flt(detail.amount)
		row_rates = {
			name: effective_rate(rate, base, amount) for name, (rate, base, amount) in totals.items()
		}
		for detail in details:
			row = taxes.get(detail.tax_row)
			if not row:
				continue
			override = item_overrides.get(detail.item_row) or {}
			add(
				groups,
				row,
				override,
				flt(detail.rate) or row_rates[detail.tax_row],
				flt(detail.taxable_amount),
				flt(detail.amount),
			)
	else:
		# Documentos sin detalle por artículo (anteriores a v16 o creados por
		# código): base = cuota / tipo, o la base de la factura si el tipo es 0.
		for row in taxes.values():
			amount = flt(row.get("base_tax_amount"))
			rate = flt(row.rate)
			base = (
				amount * 100 / rate
				if rate
				else flt(doc.get("base_net_total")) or flt(doc.get("net_total")) * conversion
			)
			add(groups, row, {}, effective_rate(rate, base, amount), base, amount)

	for group in groups.values():
		group["taxable_base"] = flt(group["taxable_base"], 2)
		group["tax_amount"] = flt(group["tax_amount"], 2)
	return list(groups.values())


# Tipos de IVA y de recargo de equivalencia vigentes o recientes, para reconocer el
# tipo de una fila de importe fijo («Actual», sin tipo) a partir de base y cuota.
KNOWN_RATES = (21, 10, 5, 4, 2, 0, 5.2, 1.75, 1.4, 0.62, 0.5, 0.26)


def effective_rate(rate: float, base: float, amount: float) -> float:
	"""Tipo de la fila. Si no lo tiene (fila de importe fijo) pero hay base y cuota,
	el que resulta de ellas, ajustado al tipo legal más cercano si difiere en menos de
	0,05 puntos (redondeos de la cuota)."""
	if rate or not base or not amount:
		return rate
	computed = abs(amount) * 100 / abs(base)
	nearest = min(KNOWN_RATES, key=lambda known: abs(known - computed))
	return nearest if abs(nearest - computed) < 0.05 else flt(computed, 2)


def add(groups: OrderedDict, row, override: dict, rate: float, base: float, amount: float) -> None:
	values = {field: row.get(field) for field in ROW_FIELDS}
	if values["es_tax_type"] in (VAT, SURCHARGE):
		for field in ("es_vat_classification", "es_operation_type"):
			if override.get(field):
				values[field] = override[field]
	key = (row.name, values["es_vat_classification"], values["es_operation_type"], abs(rate))
	group = groups.get(key)
	if group is None:
		group = groups[key] = {
			"tax_row": row.name,
			"account": row.account_head,
			"tax_type": values["es_tax_type"],
			"vat_classification": values["es_vat_classification"],
			"operation_type": values["es_operation_type"],
			"regime_key": values["es_regime_key"],
			"withholding_key": values["es_withholding_key"],
			"deductibility": values["es_deductibility"],
			"self_assessed": 1 if values["es_self_assessed"] else 0,
			"tax_rate": abs(rate),
			"taxable_base": 0.0,
			"tax_amount": 0.0,
			"unclassified": 0 if is_classified(values) else 1,
		}
	group["taxable_base"] += base
	group["tax_amount"] += amount


def is_classified(values: dict) -> bool:
	tax_type = values["es_tax_type"]
	if tax_type in (VAT, SURCHARGE):
		return bool(values["es_vat_classification"] and values["es_operation_type"])
	if tax_type == WITHHOLDING:
		return bool(values["es_withholding_key"])
	return bool(tax_type)


def item_tax_template_classification(doc) -> dict[str, dict]:
	"""Clasificación del Item Tax Template de cada línea (por nombre de fila).

	En las facturas validadas se usa la congelada en la línea al validar
	(rows.freeze_item_classification); en borradores y facturas anteriores, la
	de la plantilla actual."""
	result = {}
	for item in doc.get("items") or []:
		if doc.get("docstatus") == 1 and doc.get("es_party_country"):
			values = frappe._dict(
				es_vat_classification=item.get("es_vat_classification"),
				es_operation_type=item.get("es_operation_type"),
			)
		elif item.get("item_tax_template"):
			values = frappe.get_cached_value(
				"Item Tax Template",
				item.item_tax_template,
				["es_vat_classification", "es_operation_type"],
				as_dict=True,
			)
		else:
			continue
		if values and (values.es_vat_classification or values.es_operation_type):
			result[item.name] = {
				"es_vat_classification": values.es_vat_classification,
				"es_operation_type": values.es_operation_type,
			}
	return result
