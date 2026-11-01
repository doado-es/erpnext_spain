# Modelo 347: declaración anual de operaciones con terceras personas.
# Diseño de registro «Ejercicio 2025 y siguientes» (Orden HAC/1431/2025): registros
# de 500 posiciones, tipo 2 hoja «D» (declarado).
#
# Por tercero con NIF español y clave (A compras, B ventas), importe anual con IVA
# por encima de 3.005,06 € y desglosado por trimestres. Quedan fuera las facturas
# que van en el 349 (intracomunitarias), las exportaciones e importaciones y las que
# llevan retención (van en el 190 o el 180). No se generan los registros de
# arrendamiento de locales (hoja «I»), los cobros en metálico ni las claves C a G.
# Las compañías en el SII no presentan el 347.

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_spain.es_impuestos.codes import TAX_TYPES
from erpnext_spain.es_iva.rows import period_rows
from erpnext_spain.es_modelos import informative as inf
from erpnext_spain.es_modelos.model_349 import operation_key
from erpnext_spain.es_modelos.returns import ANNUAL, box, period_dates, set_box
from erpnext_spain.es_nif import validator

PERIODS = ANNUAL
THRESHOLD = 3005.06
LABELS = {
	"PER": "Número total de personas y entidades",
	"IMP": "Importe total anual de las operaciones",
}
EXCLUDED_OPERATIONS = ("Exportación", "Importación")
QUARTERS = ("1T", "2T", "3T", "4T")


def invoices_of_year(company: str, year: int) -> dict[str, list]:
	start, end = period_dates(year, "0A")
	by_invoice: dict[str, list] = defaultdict(list)
	for row in period_rows(company, start, end, tax_types=None):
		by_invoice[row.voucher_no].append(row)
	return by_invoice


def excluded(rows: list) -> bool:
	return any(
		operation_key(row) or row.operation_type in EXCLUDED_OPERATIONS or row.tax_type == TAX_TYPES["IRPF"]
		for row in rows
	)


def spanish_tax_id(tax_id: str | None) -> bool:
	if not tax_id or not validator.looks_spanish(tax_id):
		return False
	try:
		validator.validate_spanish_tax_id(tax_id)
	except validator.InvalidTaxID:
		return False
	return True


def compute(doc) -> tuple[dict, list[dict]]:
	grouped: dict[tuple, dict] = {}
	for rows in invoices_of_year(doc.company, doc.fiscal_year).values():
		if excluded(rows):
			continue
		head = rows[0]
		if not spanish_tax_id(head.tax_id):
			continue
		key = "B" if head.book == "Expedidas" else "A"
		line = grouped.setdefault(
			(head.party_type, head.party, key),
			{
				"party_type": head.party_type,
				"party": head.party,
				"tax_id": head.tax_id,
				"party_name": head.party_name,
				"province_code": inf.province_code(head.party_type, head.party),
				"operation_key": key,
				"amount": 0.0,
				**{f"amount_q{q}": 0.0 for q in range(1, 5)},
			},
		)
		total = flt(head.invoice_total)
		line["amount"] += total
		line[f"amount_q{QUARTERS.index(head.quarter) + 1}"] += total
	lines = []
	for line in grouped.values():
		for field in ("amount", "amount_q1", "amount_q2", "amount_q3", "amount_q4"):
			line[field] = round(line[field], 2)
		if line["amount"] <= THRESHOLD:
			continue
		if not line["province_code"]:
			line["note"] = _("Sin dirección en España: indique el código de provincia.")
		lines.append(line)
	return {}, lines


def totals(doc) -> None:
	set_box(doc, "PER", len(doc.lines))
	set_box(doc, "IMP", sum(flt(line.amount) for line in doc.lines))
	doc.result = box(doc, "IMP")


def build(doc) -> str:
	header = inf.record(
		[
			*inf.declarant_record(doc, "347"),
			(136, inf.num(box(doc, "PER"), 9)),
			(145, inf.signed_cents(box(doc, "IMP"), 16)),
			(161, inf.num(0, 9)),
			(170, inf.signed_cents(0, 16)),
		]
	)
	return inf.as_file([header, *[declared(doc, line) for line in doc.lines]])


def declared(doc, line) -> str:
	if line.operation_key not in ("A", "B"):
		frappe.throw(_("Fila {0}: solo se generan las claves A y B.").format(line.idx))
	if not line.province_code:
		frappe.throw(_("Fila {0}: falta el código de provincia de {1}.").format(line.idx, line.party_name))
	zero = inf.signed_cents(0, 16)
	return inf.record(
		[
			*inf.declarant_head(doc, "347", "2"),
			(18, inf.nif(line.tax_id)),
			(36, inf.an(line.party_name, 40)),
			(76, "D"),
			(77, inf.num(line.province_code, 2)),
			(82, line.operation_key),
			(83, inf.signed_cents(line.amount, 16)),
			(101, inf.cents(0, 15)),
			(116, zero),
			(132, inf.num(0, 4)),
			(136, inf.signed_cents(line.amount_q1, 16)),
			(152, zero),
			(168, inf.signed_cents(line.amount_q2, 16)),
			(184, zero),
			(200, inf.signed_cents(line.amount_q3, 16)),
			(216, zero),
			(232, inf.signed_cents(line.amount_q4, 16)),
			(248, zero),
			(284, zero),
			(300, inf.num(0, 6)),
		]
	)
