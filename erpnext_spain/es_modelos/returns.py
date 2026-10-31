# Modelos 303 y 111 (spec 07, primera entrega): cálculo desde el Registro
# Fiscal IVA (spec 06) y desde Tax Withholding Entry (spec 08), casillas
# revisables y fichero en el formato de importación de la AEAT (diseños de
# registro DR303e26v101 y DR111e16v18, publicados en la sede).

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.utils import flt, get_last_day, getdate

from erpnext_spain.es_impuestos.codes import TAX_TYPES

VAT, SURCHARGE = TAX_TYPES["IVA"], TAX_TYPES["RE"]
ALLOWED_ROLES = ("Accounts Manager", "System Manager")
PROGRAM_VERSION = "0100"

# --- periodos -----------------------------------------------------------------------------


def period_dates(year: int, period: str):
	if period.endswith("T"):
		quarter = int(period[0])
		start = getdate(f"{year}-{3 * quarter - 2:02d}-01")
		end = get_last_day(f"{year}-{3 * quarter:02d}-01")
	else:
		start = getdate(f"{year}-{int(period):02d}-01")
		end = get_last_day(start)
	return start, getdate(end)


def is_last_period(period: str) -> bool:
	return period in ("12", "4T")


# --- casillas -----------------------------------------------------------------------------

LABELS_303 = {
	"150": "Régimen general: base a otros tipos",
	"151": "Tipo %",
	"152": "Cuota a otros tipos",
	"01": "Régimen general: base al 4 %",
	"03": "Cuota al 4 %",
	"04": "Régimen general: base al 10 %",
	"06": "Cuota al 10 %",
	"07": "Régimen general: base al 21 %",
	"09": "Cuota al 21 %",
	"10": "Adquisiciones intracomunitarias: base",
	"11": "Adquisiciones intracomunitarias: cuota",
	"12": "Otras operaciones con inversión del sujeto pasivo: base",
	"13": "Otras operaciones con inversión del sujeto pasivo: cuota",
	"14": "Modificación de bases y cuotas: base",
	"15": "Modificación de bases y cuotas: cuota",
	"156": "Recargo de equivalencia 1,75 %: base",
	"158": "Recargo de equivalencia 1,75 %: cuota",
	"16": "Recargo de equivalencia 0,5 %: base",
	"18": "Recargo de equivalencia 0,5 %: cuota",
	"19": "Recargo de equivalencia 1,4 %: base",
	"21": "Recargo de equivalencia 1,4 %: cuota",
	"22": "Recargo de equivalencia 5,2 %: base",
	"24": "Recargo de equivalencia 5,2 %: cuota",
	"27": "Total cuota devengada",
	"28": "Operaciones interiores corrientes: base",
	"29": "Operaciones interiores corrientes: cuota deducible",
	"30": "Operaciones interiores bienes de inversión: base",
	"31": "Operaciones interiores bienes de inversión: cuota deducible",
	"32": "Importaciones corrientes: base",
	"33": "Importaciones corrientes: cuota deducible",
	"36": "Adquisiciones intracomunitarias corrientes: base",
	"37": "Adquisiciones intracomunitarias corrientes: cuota deducible",
	"38": "Adquisiciones intracomunitarias bienes de inversión: base",
	"39": "Adquisiciones intracomunitarias bienes de inversión: cuota deducible",
	"40": "Rectificación de deducciones: base",
	"41": "Rectificación de deducciones: cuota",
	"45": "Total a deducir",
	"46": "Resultado régimen general",
	"59": "Entregas intracomunitarias de bienes y servicios",
	"60": "Exportaciones y operaciones asimiladas",
	"120": "Operaciones no sujetas por reglas de localización",
	"122": "Operaciones sujetas con inversión del sujeto pasivo",
	"64": "Suma de resultados",
	"65": "% atribuible a la Administración del Estado",
	"66": "Atribuible a la Administración del Estado",
	"110": "Cuotas a compensar pendientes de periodos anteriores",
	"78": "Cuotas a compensar aplicadas en este periodo",
	"87": "Cuotas a compensar pendientes para periodos posteriores",
	"69": "Resultado de la autoliquidación",
	"71": "Resultado",
}
STANDARD_RATES = {4: ("01", "03"), 10: ("04", "06"), 21: ("07", "09")}
SURCHARGE_RATES = {1.75: ("156", "158"), 0.5: ("16", "18"), 1.4: ("19", "21"), 5.2: ("22", "24")}
INTRA = ("Adquisición intracomunitaria de bienes", "Adquisición intracomunitaria de servicios")
INVESTMENT = "Bien de inversión"

LABELS_111 = {
	"01": "Rendimientos del trabajo dinerarios: nº de perceptores",
	"02": "Rendimientos del trabajo dinerarios: importe de las percepciones",
	"03": "Rendimientos del trabajo dinerarios: importe de las retenciones",
	"07": "Actividades económicas dinerarias: nº de perceptores",
	"08": "Actividades económicas dinerarias: importe de las percepciones",
	"09": "Actividades económicas dinerarias: importe de las retenciones",
	"28": "Suma de retenciones e ingresos a cuenta",
	"29": "Resultado de anteriores declaraciones",
	"30": "Resultado a ingresar",
}
KEY_TO_111 = {
	"Trabajo": ("01", "02", "03"),
	"Actividades profesionales": ("07", "08", "09"),
	"Otras": ("07", "08", "09"),
}


def register_rows(company: str, start, end) -> list:
	return frappe.get_all(
		"ES Vat Register",
		filters={
			"company": company,
			"cancelled": 0,
			"posting_date": ["between", [start, end]],
			"tax_type": ["in", [VAT, SURCHARGE]],
		},
		fields=[
			"book",
			"tax_type",
			"vat_classification",
			"operation_type",
			"deductibility",
			"self_assessed",
			"invoice_type",
			"taxable_base",
			"tax_rate",
			"tax_amount",
			"deductible_amount",
		],
	)


def compute_303(company: str, year: int, period: str) -> dict[str, float]:
	start, end = period_dates(year, period)
	boxes: dict[str, float] = defaultdict(float)
	other_rates = set()
	for row in register_rows(company, start, end):
		base, quota, rate = flt(row.taxable_base), flt(row.tax_amount), flt(row.tax_rate)
		rectification = (row.invoice_type or "").startswith("R")
		classification = row.vat_classification or "S1"
		if row.book == "Expedidas":
			if row.tax_type == SURCHARGE:
				base_box, quota_box = (
					("14", "15") if rectification else SURCHARGE_RATES.get(round(rate, 2), ("22", "24"))
				)
				boxes[base_box] += base
				boxes[quota_box] += quota
				continue
			if classification == "E5":
				boxes["59"] += base
			elif classification == "E2":
				boxes["60"] += base
			elif classification == "N2":
				boxes["120"] += base
			elif classification == "S2":
				boxes["122"] += base
			if classification != "S1":
				continue
			if rectification:
				boxes["14"] += base
				boxes["15"] += quota
			elif round(rate) in STANDARD_RATES and abs(rate - round(rate)) < 0.001:
				base_box, quota_box = STANDARD_RATES[round(rate)]
				boxes[base_box] += base
				boxes[quota_box] += quota
			else:
				other_rates.add(rate)
				boxes["150"] += base
				boxes["152"] += quota
		else:
			if row.self_assessed:
				base_box, quota_box = ("10", "11") if row.operation_type in INTRA else ("12", "13")
				boxes[base_box] += base
				boxes[quota_box] += quota
				continue
			deductible = flt(row.deductible_amount)
			if not deductible and row.deductibility == "No deducible":
				continue
			investment = row.deductibility == INVESTMENT
			if rectification:
				pair = ("40", "41")
			elif row.operation_type in INTRA:
				pair = ("38", "39") if investment else ("36", "37")
			elif row.operation_type == "Importación":
				pair = ("34", "35") if investment else ("32", "33")
			else:
				pair = ("30", "31") if investment else ("28", "29")
			boxes[pair[0]] += base
			boxes[pair[1]] += deductible
	if len(other_rates) == 1:
		boxes["151"] = other_rates.pop()
	boxes["27"] = sum(boxes[b] for b in ("152", "03", "06", "09", "11", "13", "15", "158", "18", "21", "24"))
	boxes["45"] = sum(boxes[b] for b in ("29", "31", "33", "35", "37", "39", "41"))
	boxes["46"] = boxes["27"] - boxes["45"]
	return {k: round(v, 2) for k, v in boxes.items()}


def compute_111(company: str, year: int, period: str) -> dict[str, float]:
	start, end = period_dates(year, period)
	entry = frappe.qb.DocType("Tax Withholding Entry")
	category = frappe.qb.DocType("Tax Withholding Category")
	rows = (
		frappe.qb.from_(entry)
		.join(category)
		.on(category.name == entry.tax_withholding_category)
		.select(
			category.es_irpf_key.as_("key"),
			Count(entry.party).distinct().as_("parties"),
			Sum(entry.taxable_amount).as_("taxable"),
			Sum(entry.withholding_amount).as_("withheld"),
		)
		.where(entry.company == company)
		.where(entry.docstatus == 1)
		.where(entry.status.notin(["Cancelled", "Duplicate"]))
		.where(entry.withholding_amount != 0)
		.where(category.es_tax_model == "111")
		.where(entry.withholding_date[start:end])
		.groupby(category.es_irpf_key)
	).run(as_dict=True)
	boxes: dict[str, float] = defaultdict(float)
	for row in rows:
		count, taxable, withheld = KEY_TO_111.get(row.key, KEY_TO_111["Otras"])
		boxes[count] += flt(row.parties)
		boxes[taxable] += flt(row.taxable)
		boxes[withheld] += flt(row.withheld)
	boxes["28"] = sum(boxes[b] for b in ("03", "09"))
	return {k: round(v, 2) for k, v in boxes.items()}


# --- documento ----------------------------------------------------------------------------


def calculate(doc) -> None:
	labels = LABELS_303 if doc.tax_model == "303" else LABELS_111
	values = (
		compute_303(doc.company, doc.fiscal_year, doc.period)
		if doc.tax_model == "303"
		else compute_111(doc.company, doc.fiscal_year, doc.period)
	)
	manual = {row.box: row.amount for row in doc.boxes if row.manual}
	doc.set("boxes", [])
	for box, label in labels.items():
		computed = flt(values.get(box))
		doc.append(
			"boxes",
			{
				"box": box,
				"label": label,
				"computed": computed,
				"amount": manual.get(box, computed),
				"manual": 1 if box in manual else 0,
			},
		)


def box(doc, code: str) -> float:
	return next((flt(row.amount) for row in doc.boxes if row.box == code), 0.0)


def set_box(doc, code: str, value: float) -> None:
	for row in doc.boxes:
		if row.box == code and not row.manual:
			row.amount = round(value, 2)


def compute_totals(doc) -> None:
	"""Totales y resultado a partir de las casillas (también tras corregirlas a mano)."""
	if doc.tax_model == "303":
		set_box(
			doc,
			"27",
			sum(box(doc, b) for b in ("152", "03", "06", "09", "11", "13", "15", "158", "18", "21", "24")),
		)
		set_box(doc, "45", sum(box(doc, b) for b in ("29", "31", "33", "35", "37", "39", "41")))
		set_box(doc, "46", box(doc, "27") - box(doc, "45"))
		set_box(doc, "64", box(doc, "46"))
		set_box(doc, "65", 100)
		set_box(doc, "66", box(doc, "64") * box(doc, "65") / 100)
		set_box(doc, "110", flt(doc.previous_compensation))
		set_box(doc, "78", flt(doc.applied_compensation))
		set_box(doc, "87", box(doc, "110") - box(doc, "78"))
		set_box(doc, "69", box(doc, "66") - box(doc, "78"))
		set_box(doc, "71", box(doc, "69"))
		doc.result = box(doc, "71")
	else:
		set_box(doc, "28", box(doc, "03") + box(doc, "09"))
		set_box(doc, "30", box(doc, "28") - box(doc, "29"))
		doc.result = box(doc, "30")


@frappe.whitelist(methods=["POST"])
def recalculate(name: str) -> None:
	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Solo un usuario con rol Accounts Manager puede recalcular declaraciones."),
			frappe.PermissionError,
		)
	doc = frappe.get_doc("ES Tax Return", name)
	doc.check_permission("write")
	calculate(doc)
	doc.save()


# --- fichero AEAT ------------------------------------------------------------------------------


def alpha(value, length: int) -> str:
	from erpnext_spain.es_sepa.confirming import alpha as ascii_alpha

	return ascii_alpha((value or "").upper(), length)


def unsigned(value: float, length: int) -> str:
	return str(round(abs(flt(value)) * 100)).rjust(length, "0")[-length:]


def signed(value: float, length: int) -> str:
	"""Numérico con signo de la AEAT: negativo con «N» en la primera posición."""
	digits = unsigned(value, length - 1 if flt(value) < 0 else length)
	return f"N{digits}" if flt(value) < 0 else digits


def page(length: int, fields: list[tuple[int, str]]) -> str:
	"""Página de longitud fija: [(posición 1-based, texto)]."""
	chars = [" "] * length
	for position, value in fields:
		for offset, char in enumerate(value):
			chars[position - 1 + offset] = char
	return "".join(chars)


def envelope(model: str, year: int, period: str, pages: list[str]) -> str:
	developer = (frappe.db.get_single_value("ES Settings", "sif_nif") or "").upper()
	head = f"<T{model}0{year}{period}0000><AUX>{' ' * 70}{PROGRAM_VERSION}{' ' * 4}{alpha(developer, 9)}{' ' * 213}</AUX>"
	return head + "".join(pages) + f"</T{model}0{year}{period}0000>"


def identification(doc) -> tuple[str, str]:
	nif = (frappe.get_cached_value("Company", doc.company, "tax_id") or "").upper().replace("ES", "", 1)[:9]
	name = frappe.get_cached_value("Company", doc.company, "company_name")
	return nif, name


# Posiciones de las casillas de importe de la página 01 del 303 (DR303e26v101).
PAGE_303_01 = {
	"150": (131, 17, "N"), "151": (148, 5, "U"), "152": (153, 17, "N"),
	"01": (209, 17, "N"), "03": (231, 17, "N"), "04": (287, 17, "N"), "06": (309, 17, "N"),
	"07": (326, 17, "N"), "09": (348, 17, "N"), "10": (365, 17, "N"), "11": (382, 17, "N"),
	"12": (399, 17, "N"), "13": (416, 17, "N"), "14": (433, 17, "N"), "15": (450, 17, "N"),
	"156": (467, 17, "N"), "158": (489, 17, "N"), "16": (545, 17, "N"), "18": (567, 17, "N"),
	"19": (584, 17, "N"), "21": (606, 17, "N"), "22": (623, 17, "N"), "24": (645, 17, "N"),
	"27": (696, 17, "N"), "28": (713, 17, "N"), "29": (730, 17, "N"), "30": (747, 17, "N"),
	"31": (764, 17, "N"), "32": (781, 17, "N"), "33": (798, 17, "N"), "36": (849, 17, "N"),
	"37": (866, 17, "N"), "38": (883, 17, "N"), "39": (900, 17, "N"), "40": (917, 17, "N"),
	"41": (934, 17, "N"), "45": (1002, 17, "N"), "46": (1019, 17, "N"),
}  # fmt: skip
CONSTANT_RATES_303 = {
	226: "00400",
	304: "01000",
	343: "02100",
	484: "00175",
	523: "00050",
	601: "00140",
	640: "00520",
	187: "00000",
	265: "00000",
	562: "00000",
}
PAGE_303_03 = {
	"59": (12, 17, "N"), "60": (29, 17, "N"), "120": (46, 17, "N"), "122": (63, 17, "N"),
	"64": (199, 17, "N"), "65": (216, 5, "U"), "66": (221, 17, "N"), "110": (255, 17, "U"),
	"78": (272, 17, "U"), "87": (289, 17, "U"), "69": (340, 17, "N"), "71": (408, 17, "N"),
}  # fmt: skip
PAGE_111_01 = {
	"01": (109, 8, "C"), "02": (117, 17, "U"), "03": (134, 17, "U"),
	"07": (193, 8, "C"), "08": (201, 17, "U"), "09": (218, 17, "U"),
	"28": (487, 17, "U"), "29": (504, 17, "N"), "30": (521, 17, "U"),
}  # fmt: skip


def amount_fields(doc, positions: dict) -> list[tuple[int, str]]:
	fields = []
	for code, (position, length, kind) in positions.items():
		value = box(doc, code)
		if kind == "C":
			fields.append((position, str(int(value)).rjust(length, "0")))
		elif kind == "U":
			fields.append((position, unsigned(value, length)))
		else:
			fields.append((position, signed(value, length)))
	return fields


def build_303(doc) -> str:
	nif, name = identification(doc)
	last = is_last_period(doc.period)
	sii = frappe.get_cached_value("Company", doc.company, "es_sii_enabled")
	flags = [
		(109, "2"), (110, "2"), (111, "3"), (112, "2"), (113, "2"), (114, "2"), (117, "2"),
		(127, "1" if sii else "2"),
		(128, ("1" if sii else "2") if last else "0"),
		(129, "1" if last else "0"),
		(130, "0" if doc.period in ("1T", "2T", "3T", "4T", "01") else "2"),
	]  # fmt: skip
	page1 = page(
		1581,
		[
			(1, "<T30301000>"),
			(13, doc.declaration_type[0]),
			(14, alpha(nif, 9)),
			(23, alpha(name, 80)),
			(103, str(doc.fiscal_year)),
			(107, doc.period),
			*flags,
			*[(position, value) for position, value in CONSTANT_RATES_303.items()],
			*amount_fields(doc, PAGE_303_01),
			(1570, "</T30301000>"),
		],
	)
	page3 = page(
		1017,
		[
			(1, "<T30303000>"),
			*amount_fields(doc, PAGE_303_03),
			(425, "X" if doc.declaration_type.startswith("N") else " "),
			(1006, "</T30303000>"),
		],
	)
	return envelope("303", doc.fiscal_year, doc.period, [page1, page3])


def build_111(doc) -> str:
	nif, name = identification(doc)
	page1 = page(
		1000,
		[
			(1, "<T11101000>"),
			(13, doc.declaration_type[0]),
			(14, alpha(nif, 9)),
			(23, alpha(name, 60)),
			(103, str(doc.fiscal_year)),
			(107, doc.period),
			*amount_fields(doc, PAGE_111_01),
			(989, "</T11101000>"),
		],
	)
	return envelope("111", doc.fiscal_year, doc.period, [page1])


def attach_file(doc) -> None:
	content = build_303(doc) if doc.tax_model == "303" else build_111(doc)
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.tax_model}_{doc.fiscal_year}_{doc.period}.txt",
			"content": content.encode("latin-1"),
			"is_private": 1,
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
		}
	).insert(ignore_permissions=True)
	doc.db_set("aeat_file", file.file_url)
