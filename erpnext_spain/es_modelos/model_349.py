# Modelo 349: declaración recapitulativa de operaciones intracomunitarias.
# Diseño de registro del anexo de la Orden HAC/174/2020 (2020 y siguientes):
# registros de 500 posiciones; tipo 2 = operador o rectificación.
#
# Sale del desglose fiscal de las facturas (es_iva/rows.py):
#   E  entregas intracomunitarias exentas (calificación E5)
#   S  servicios prestados a empresarios de la UE (no sujetos por localización, N2)
#   A  adquisiciones intracomunitarias de bienes (fila autorrepercutida)
#   I  adquisiciones intracomunitarias de servicios (fila autorrepercutida)
# Las rectificativas de facturas de periodos anteriores van como rectificaciones del
# periodo de la factura original. Las operaciones triangulares (T), las de ventas en
# consigna (R, D, C) y las de importación exenta (M, H) se añaden a mano.

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext_spain.es_iva.rows import period_rows
from erpnext_spain.es_modelos import informative as inf
from erpnext_spain.es_modelos.returns import MONTHLY_OR_QUARTERLY, box, period_dates, set_box

PERIODS = MONTHLY_OR_QUARTERLY
LABELS = {
	"OPE": "Número total de operadores intracomunitarios",
	"IMP": "Importe de las operaciones intracomunitarias",
	"REC": "Número total de operadores con rectificaciones",
	"IMR": "Importe de las rectificaciones",
}
OPERATION_KEYS = ("E", "M", "H", "A", "T", "S", "I", "R", "D", "C")


def operation_key(row) -> str | None:
	if row.book == "Expedidas":
		if row.vat_classification == "E5":
			return "E"
		if row.vat_classification == "N2" and row.id_type == "02":
			return "S"
		return None
	if row.self_assessed and row.operation_type == "Adquisición intracomunitaria de bienes":
		return "A"
	if row.self_assessed and row.operation_type == "Adquisición intracomunitaria de servicios":
		return "I"
	return None


def period_of(date, period: str) -> str:
	date = getdate(date)
	return f"{(date.month - 1) // 3 + 1}T" if period.endswith("T") else f"{date.month:02d}"


def compute(doc) -> tuple[dict, list[dict]]:
	start, end = period_dates(doc.fiscal_year, doc.period)
	current: dict[tuple, dict] = {}
	rectified: dict[tuple, float] = defaultdict(float)
	originals = {}
	for row in period_rows(doc.company, start, end):
		key = operation_key(row)
		if not key:
			continue
		party = (row.party_type, row.party, key)
		original = row.rectified_invoice
		if original and original not in originals:
			originals[original] = frappe.db.get_value(row.voucher_type, original, "posting_date")
		original_date = originals.get(original) if original else None
		if original_date and getdate(original_date) < start:
			year = getdate(original_date).year
			rectified[(*party, year, period_of(original_date, doc.period))] += flt(row.taxable_base)
			continue
		line = current.setdefault(party, operator(row, key))
		line["amount"] += flt(row.taxable_base)

	lines = []
	for line in current.values():
		line["amount"] = round(line["amount"], 2)
		if line["amount"] < 0:
			line["note"] = _("Importe negativo: revise las rectificativas del periodo.")
		if abs(line["amount"]) >= 0.005:
			lines.append(line)
	for (party_type, party, key, year, period), delta in rectified.items():
		previous = declared_amount(doc, party_type, party, key, year, period)
		line = operator_for(party_type, party, key)
		line.update(
			{
				"rectified_year": year,
				"rectified_period": period,
				"previous_amount": previous,
				"amount": round(flt(previous) + delta, 2),
			}
		)
		if previous is None:
			line["previous_amount"] = 0
			line["note"] = _("No hay un 349 de {0}/{1} con este operador: indique la base declarada.").format(
				period, year
			)
		lines.append(line)
	return {}, lines


def operator(row, key: str) -> dict:
	return {
		"party_type": row.party_type,
		"party": row.party,
		"tax_id": row.tax_id,
		"party_name": row.party_name,
		"country_code": inf.vat_number(row.tax_id)[0],
		"operation_key": key,
		"amount": 0.0,
	}


def operator_for(party_type: str, party: str, key: str) -> dict:
	field = "supplier_name" if party_type == "Supplier" else "customer_name"
	tax_id = frappe.get_cached_value(party_type, party, "tax_id")
	return {
		"party_type": party_type,
		"party": party,
		"tax_id": tax_id,
		"party_name": frappe.get_cached_value(party_type, party, field) or party,
		"country_code": inf.vat_number(tax_id)[0],
		"operation_key": key,
	}


def declared_amount(doc, party_type: str, party: str, key: str, year: int, period: str) -> float | None:
	"""Base declarada para el operador en el 349 validado de ese periodo (el último)."""
	returns = frappe.get_all(
		"ES Tax Return",
		filters={
			"company": doc.company,
			"tax_model": "349",
			"fiscal_year": year,
			"period": period,
			"docstatus": 1,
		},
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	if not returns:
		return None
	amount = frappe.db.get_value(
		"ES Tax Return Line",
		{
			"parent": returns[0],
			"parenttype": "ES Tax Return",
			"party_type": party_type,
			"party": party,
			"operation_key": key,
			"rectified_period": ["is", "not set"],
		},
		"amount",
	)
	return flt(amount) if amount is not None else None


def is_rectification(line) -> bool:
	return bool(line.rectified_period)


def totals(doc) -> None:
	operators = [line for line in doc.lines if not is_rectification(line)]
	rectifications = [line for line in doc.lines if is_rectification(line)]
	set_box(doc, "OPE", len(operators))
	set_box(doc, "IMP", sum(flt(line.amount) for line in operators))
	set_box(doc, "REC", len(rectifications))
	set_box(doc, "IMR", sum(flt(line.amount) for line in rectifications))
	doc.result = box(doc, "IMP")


def build(doc) -> str:
	header = inf.record(
		[
			*inf.declarant_record(doc, "349", support=None),
			(136, doc.period),
			(138, inf.num(box(doc, "OPE"), 9)),
			(147, inf.cents(box(doc, "IMP"), 15)),
			(162, inf.num(box(doc, "REC"), 9)),
			(171, inf.cents(box(doc, "IMR"), 15)),
			(186, "X" if doc.change_of_periodicity else " "),
		]
	)
	return inf.as_file([header, *[operation(doc, line) for line in doc.lines]])


def operation(doc, line) -> str:
	if line.operation_key not in OPERATION_KEYS:
		frappe.throw(_("Fila {0}: clave de operación {1} no válida.").format(line.idx, line.operation_key))
	country, number = inf.vat_number(line.tax_id)
	if not country or not number:
		frappe.throw(_("Fila {0}: {1} no tiene NIF-IVA europeo.").format(line.idx, line.party_name))
	if flt(line.amount) < 0 and not is_rectification(line):
		frappe.throw(_("Fila {0}: el importe de una operación no puede ser negativo.").format(line.idx))
	fields = [
		*inf.declarant_head(doc, "349", "2"),
		(76, inf.an(country, 2)),
		(78, inf.an(number, 15)),
		(93, inf.an(line.party_name, 40)),
		(133, line.operation_key),
	]
	if is_rectification(line):
		fields += [
			(147, inf.num(line.rectified_year, 4)),
			(151, inf.an(line.rectified_period, 2)),
			(153, inf.cents(line.amount, 13)),
			(166, inf.cents(line.previous_amount, 13)),
		]
	else:
		fields.append((134, inf.cents(line.amount, 13)))
	return inf.record(fields)
