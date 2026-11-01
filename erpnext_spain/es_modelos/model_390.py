# Modelo 390: declaración-resumen anual del IVA.
# Diseño de registro dr390e2026 (vers. 1.00, ejercicio 2026), convertido a datos
# en layouts/dr390e2026.json: posición, longitud, tipo, constantes y casillas de
# cada campo de cada página.
#
# Casillas del régimen general calculadas con el desglose fiscal de las facturas
# del año (como el 303), el resultado de la liquidación anual, los resultados de
# los 303 del ejercicio y el volumen de operaciones. Los datos estadísticos
# (actividad, IAE, CNAE), las prorratas y los regímenes especiales se completan en
# el formulario de la AEAT. Se generan las páginas 01, 02, 02 bis, 03, 04, 06 y 07
# (la 05 es del régimen simplificado y la 08 de los sectores diferenciados).
# Las compañías del SII no presentan el 390.

import json
from collections import defaultdict
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_spain.es_modelos.returns import (
	ANNUAL,
	INTRA,
	INVESTMENT,
	SURCHARGE,
	alpha,
	box,
	envelope,
	identification,
	period_dates,
	register_rows,
	set_box,
	signed,
	unsigned,
)

PERIODS = ANNUAL
LAYOUT = Path(__file__).parent / "layouts" / "dr390e2026.json"
PAGES = ("01000", "02000", "02B00", "03000", "04000", "06000", "07000")

RATES = (4, 10, 21)
# (base, cuota) por tipo de cada bloque.
SALES = {4: ("01", "02"), 10: ("03", "04"), 21: ("05", "06")}
AIB_ACCRUED = {4: ("21", "22"), 10: ("23", "24"), 21: ("25", "26")}
AIS_ACCRUED = {4: ("545", "546"), 10: ("547", "548"), 21: ("551", "552")}
SURCHARGES = {0.5: ("35", "36"), 1.4: ("599", "600"), 5.2: ("601", "602"), 1.75: ("41", "42")}
DEDUCTIBLE = {
	# (operación, inversión): ({tipo: (base, cuota)}, (total base, total cuota))
	("interior", False): ({4: ("190", "191"), 10: ("603", "604"), 21: ("605", "606")}, ("48", "49")),
	("interior", True): ({4: ("196", "197"), 10: ("611", "612"), 21: ("613", "614")}, ("50", "51")),
	("import", False): ({4: ("202", "203"), 10: ("619", "620"), 21: ("621", "622")}, ("52", "53")),
	("import", True): ({4: ("208", "209"), 10: ("623", "624"), 21: ("625", "626")}, ("54", "55")),
	("aib", False): ({4: ("214", "215"), 10: ("627", "628"), 21: ("629", "630")}, ("56", "57")),
	("aib", True): ({4: ("220", "221"), 10: ("631", "632"), 21: ("633", "634")}, ("58", "59")),
	("ais", False): ({4: ("587", "588"), 10: ("635", "636"), 21: ("637", "638")}, ("597", "598")),
}
EXEMPT_WITH_DEDUCTION = ("E2", "E3", "E4", "E5", "E6")

LABELS = {
	"01": "Régimen ordinario 4 %: base", "02": "Régimen ordinario 4 %: cuota",
	"03": "Régimen ordinario 10 %: base", "04": "Régimen ordinario 10 %: cuota",
	"05": "Régimen ordinario 21 %: base", "06": "Régimen ordinario 21 %: cuota",
	"21": "Adquisiciones intracomunitarias de bienes 4 %: base", "22": "Adquisiciones intracomunitarias de bienes 4 %: cuota",
	"23": "Adquisiciones intracomunitarias de bienes 10 %: base", "24": "Adquisiciones intracomunitarias de bienes 10 %: cuota",
	"25": "Adquisiciones intracomunitarias de bienes 21 %: base", "26": "Adquisiciones intracomunitarias de bienes 21 %: cuota",
	"545": "Adquisiciones intracomunitarias de servicios 4 %: base", "546": "Adquisiciones intracomunitarias de servicios 4 %: cuota",
	"547": "Adquisiciones intracomunitarias de servicios 10 %: base", "548": "Adquisiciones intracomunitarias de servicios 10 %: cuota",
	"551": "Adquisiciones intracomunitarias de servicios 21 %: base", "552": "Adquisiciones intracomunitarias de servicios 21 %: cuota",
	"27": "IVA devengado por inversión del sujeto pasivo: base", "28": "IVA devengado por inversión del sujeto pasivo: cuota",
	"29": "Modificación de bases y cuotas: base", "30": "Modificación de bases y cuotas: cuota",
	"33": "Total bases IVA devengado", "34": "Total cuotas IVA devengado",
	"35": "Recargo de equivalencia 0,5 %: base", "36": "Recargo de equivalencia 0,5 %: cuota",
	"599": "Recargo de equivalencia 1,4 %: base", "600": "Recargo de equivalencia 1,4 %: cuota",
	"601": "Recargo de equivalencia 5,2 %: base", "602": "Recargo de equivalencia 5,2 %: cuota",
	"41": "Recargo de equivalencia 1,75 %: base", "42": "Recargo de equivalencia 1,75 %: cuota",
	"43": "Modificación de recargo de equivalencia: base", "44": "Modificación de recargo de equivalencia: cuota",
	"47": "Total cuotas IVA y recargo de equivalencia",
	"190": "Interiores corrientes 4 %: base", "191": "Interiores corrientes 4 %: cuota",
	"603": "Interiores corrientes 10 %: base", "604": "Interiores corrientes 10 %: cuota",
	"605": "Interiores corrientes 21 %: base", "606": "Interiores corrientes 21 %: cuota",
	"48": "Total interiores corrientes: base", "49": "Total interiores corrientes: cuota",
	"196": "Interiores bienes de inversión 4 %: base", "197": "Interiores bienes de inversión 4 %: cuota",
	"611": "Interiores bienes de inversión 10 %: base", "612": "Interiores bienes de inversión 10 %: cuota",
	"613": "Interiores bienes de inversión 21 %: base", "614": "Interiores bienes de inversión 21 %: cuota",
	"50": "Total interiores bienes de inversión: base", "51": "Total interiores bienes de inversión: cuota",
	"202": "Importaciones corrientes 4 %: base", "203": "Importaciones corrientes 4 %: cuota",
	"619": "Importaciones corrientes 10 %: base", "620": "Importaciones corrientes 10 %: cuota",
	"621": "Importaciones corrientes 21 %: base", "622": "Importaciones corrientes 21 %: cuota",
	"52": "Total importaciones corrientes: base", "53": "Total importaciones corrientes: cuota",
	"208": "Importaciones bienes de inversión 4 %: base", "209": "Importaciones bienes de inversión 4 %: cuota",
	"623": "Importaciones bienes de inversión 10 %: base", "624": "Importaciones bienes de inversión 10 %: cuota",
	"625": "Importaciones bienes de inversión 21 %: base", "626": "Importaciones bienes de inversión 21 %: cuota",
	"54": "Total importaciones bienes de inversión: base", "55": "Total importaciones bienes de inversión: cuota",
	"214": "Adquisiciones intracomunitarias de bienes corrientes 4 %: base", "215": "Adquisiciones intracomunitarias de bienes corrientes 4 %: cuota",
	"627": "Adquisiciones intracomunitarias de bienes corrientes 10 %: base", "628": "Adquisiciones intracomunitarias de bienes corrientes 10 %: cuota",
	"629": "Adquisiciones intracomunitarias de bienes corrientes 21 %: base", "630": "Adquisiciones intracomunitarias de bienes corrientes 21 %: cuota",
	"56": "Total adquisiciones intracomunitarias de bienes corrientes: base", "57": "Total adquisiciones intracomunitarias de bienes corrientes: cuota",
	"220": "Adquisiciones intracomunitarias de bienes de inversión 4 %: base", "221": "Adquisiciones intracomunitarias de bienes de inversión 4 %: cuota",
	"631": "Adquisiciones intracomunitarias de bienes de inversión 10 %: base", "632": "Adquisiciones intracomunitarias de bienes de inversión 10 %: cuota",
	"633": "Adquisiciones intracomunitarias de bienes de inversión 21 %: base", "634": "Adquisiciones intracomunitarias de bienes de inversión 21 %: cuota",
	"58": "Total adquisiciones intracomunitarias de bienes de inversión: base", "59": "Total adquisiciones intracomunitarias de bienes de inversión: cuota",
	"587": "Adquisiciones intracomunitarias de servicios 4 %: base", "588": "Adquisiciones intracomunitarias de servicios 4 %: cuota",
	"635": "Adquisiciones intracomunitarias de servicios 10 %: base", "636": "Adquisiciones intracomunitarias de servicios 10 %: cuota",
	"637": "Adquisiciones intracomunitarias de servicios 21 %: base", "638": "Adquisiciones intracomunitarias de servicios 21 %: cuota",
	"597": "Total adquisiciones intracomunitarias de servicios: base", "598": "Total adquisiciones intracomunitarias de servicios: cuota",
	"639": "Rectificación de deducciones: base", "62": "Rectificación de deducciones: cuota",
	"64": "Suma de deducciones",
	"65": "Resultado régimen general",
	"84": "Suma de resultados",
	"85": "Compensación de cuotas del ejercicio anterior",
	"86": "Resultado de la liquidación",
	"87": "Territorio común (%)",
	"92": "Resultado atribuible a territorio común",
	"93": "Compensación de cuotas del ejercicio anterior atribuible a territorio común",
	"94": "Resultado de la liquidación anual atribuible a territorio común",
	"95": "Total resultados a ingresar en las autoliquidaciones del ejercicio",
	"97": "Resultado del último periodo: a compensar",
	"98": "Resultado del último periodo: a devolver",
	"99": "Volumen: operaciones en régimen general",
	"103": "Volumen: entregas intracomunitarias de bienes y servicios",
	"104": "Volumen: exportaciones y otras exentas con derecho a deducción",
	"105": "Volumen: exentas sin derecho a deducción",
	"110": "Volumen: no sujetas por reglas de localización",
	"125": "Volumen: sujetas con inversión del sujeto pasivo",
	"108": "Total volumen de operaciones",
}  # fmt: skip

ACCRUED_BASES = ("01", "03", "05", "21", "23", "25", "545", "547", "551", "27", "29")
ACCRUED_QUOTAS = ("02", "04", "06", "22", "24", "26", "546", "548", "552", "28", "30")
SURCHARGE_QUOTAS = ("36", "600", "602", "42", "44")
DEDUCTION_QUOTAS = ("49", "51", "53", "55", "57", "59", "598", "62")
VOLUME = ("99", "103", "104", "105", "110", "125")


def rate_of(row) -> int | None:
	rate = round(flt(row.tax_rate))
	return rate if rate in RATES and abs(flt(row.tax_rate) - rate) < 0.001 else None


def compute(doc) -> tuple[dict, None]:
	start, end = period_dates(doc.fiscal_year, "0A")
	boxes: dict[str, float] = defaultdict(float)
	unusual = set()

	def add(pair, base, quota):
		boxes[pair[0]] += base
		boxes[pair[1]] += quota

	for row in register_rows(doc.company, start, end):
		base, quota = flt(row.taxable_base), flt(row.tax_amount)
		rectification = (row.invoice_type or "").startswith("R")
		classification = row.vat_classification or "S1"
		rate = rate_of(row)
		if row.book == "Expedidas":
			if row.tax_type == SURCHARGE:
				pair = ("43", "44") if rectification else SURCHARGES.get(round(flt(row.tax_rate), 2))
				if pair:
					add(pair, base, quota)
				else:
					unusual.add(f"RE {row.tax_rate}")
				continue
			volume_box = {"E5": "103", "S2": "125", "E1": "105"}.get(classification)
			if classification == "N2":
				volume_box = "103" if row.id_type == "02" else "110"
			elif classification in EXEMPT_WITH_DEDUCTION and classification != "E5":
				volume_box = "104"
			elif classification == "S1":
				volume_box = "99"
			if volume_box:
				boxes[volume_box] += base
			if classification != "S1":
				continue
			if rectification:
				add(("29", "30"), base, quota)
			elif rate:
				add(SALES[rate], base, quota)
			else:
				unusual.add(f"{row.tax_rate} %")
			continue
		# Recibidas
		if row.self_assessed:
			if row.operation_type in INTRA:
				table = AIB_ACCRUED if row.operation_type == INTRA[0] else AIS_ACCRUED
				if rate:
					add(table[rate], base, quota)
				else:
					unusual.add(f"{row.tax_rate} %")
			else:
				add(("27", "28"), base, quota)
			continue
		deductible = flt(row.deductible_amount)
		if not deductible and row.deductibility == "No deducible":
			continue
		if rectification:
			add(("639", "62"), base, deductible)
			continue
		investment = row.deductibility == INVESTMENT
		operation = (
			"aib"
			if row.operation_type == INTRA[0]
			else "ais"
			if row.operation_type == INTRA[1]
			else "import"
			if row.operation_type == "Importación"
			else "interior"
		)
		by_rate, total = DEDUCTIBLE.get((operation, investment if operation != "ais" else False))
		if rate:
			add(by_rate[rate], base, deductible)
		else:
			unusual.add(f"{row.tax_rate} %")
		add(total, base, deductible)

	values = {k: round(v, 2) for k, v in boxes.items()}
	values.update(previous_returns(doc))
	if unusual:
		frappe.msgprint(
			_("Hay operaciones a tipos sin casilla en el 390 ({0}): revíselas.").format(
				", ".join(sorted(unusual))
			),
			indicator="orange",
		)
	return values, None


def previous_returns(doc) -> dict[str, float]:
	"""[95], [97] y [98] desde los 303 validados del ejercicio."""
	returns = frappe.get_all(
		"ES Tax Return",
		filters={"company": doc.company, "tax_model": "303", "fiscal_year": doc.fiscal_year, "docstatus": 1},
		fields=["period", "result", "declaration_type"],
		order_by="creation",
	)
	values = {"95": round(sum(flt(r.result) for r in returns if flt(r.result) > 0), 2)}
	last = [r for r in returns if r.period in ("12", "4T")]
	if last and flt(last[-1].result) < 0:
		key = "98" if (last[-1].declaration_type or "").startswith(("D", "V", "X")) else "97"
		values[key] = round(abs(flt(last[-1].result)), 2)
	return values


def totals(doc) -> None:
	set_box(doc, "33", sum(box(doc, b) for b in ACCRUED_BASES))
	set_box(doc, "34", sum(box(doc, b) for b in ACCRUED_QUOTAS))
	set_box(doc, "47", box(doc, "34") + sum(box(doc, b) for b in SURCHARGE_QUOTAS))
	set_box(doc, "64", sum(box(doc, b) for b in DEDUCTION_QUOTAS))
	set_box(doc, "65", box(doc, "47") - box(doc, "64"))
	set_box(doc, "84", box(doc, "65"))
	set_box(doc, "85", flt(doc.previous_compensation))
	set_box(doc, "86", box(doc, "84") - box(doc, "85"))
	set_box(doc, "87", 100)
	set_box(doc, "92", box(doc, "84"))
	set_box(doc, "93", box(doc, "85"))
	set_box(doc, "94", box(doc, "86"))
	set_box(doc, "108", sum(box(doc, b) for b in VOLUME))
	doc.result = box(doc, "86")


def layout() -> dict:
	return json.loads(LAYOUT.read_text(encoding="utf-8"))["pages"]


def build(doc) -> str:
	pages = layout()
	values = {row.box: flt(row.amount) for row in doc.boxes}
	return envelope(
		"390", doc.fiscal_year, "0A", [render(doc, page_id, pages[page_id], values) for page_id in PAGES]
	)


def render(doc, page_id: str, page: dict, values: dict) -> str:
	chars = []
	for field in page["fields"]:
		chars.append(field_value(doc, page_id, field, values))
	text = "".join(chars)
	if len(text) != page["length"]:
		frappe.throw(_("Error interno al generar la página {0} del 390.").format(page_id))
	return text


def field_value(doc, page_id: str, field: dict, values: dict) -> str:
	length, kind = field["len"], field["type"]
	if "const" in field:
		return field["const"]
	special = page_01(doc, field) if page_id == "01000" else None
	if special is not None:
		return special.ljust(length)[:length]
	if field.get("boxes"):
		value = values.get(field["boxes"][0], 0)
		return signed(value, length) if kind == "N" else unsigned(value, length)
	return "0" * length if kind in ("Num", "N") else " " * length


def page_01(doc, field: dict) -> str | None:
	nif, name = identification(doc)
	flags_no = {130, 131, 132, 133}
	position = field["pos"]
	if position == 14:
		return alpha(nif, 9)
	if position == 23:
		return alpha(name, 60)
	if position == 103:
		return str(doc.fiscal_year)
	if position in (109, 110, 118, 119, 120, 134, 135):
		return "0"
	if position in flags_no:
		return "2"
	if position == 431:
		has_347 = frappe.db.exists(
			"ES Tax Return",
			{"company": doc.company, "tax_model": "347", "fiscal_year": doc.fiscal_year, "docstatus": 1},
		)
		return "1" if has_347 else "0"
	return None
