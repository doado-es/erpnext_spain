# Modelo 115: retenciones e ingresos a cuenta sobre arrendamientos de inmuebles urbanos.
# Diseño de registro DR115e15v13 (versión 1.3, ejercicios 2019 y siguientes).

from frappe.utils import flt

from erpnext_spain.es_modelos import informative
from erpnext_spain.es_modelos.returns import (
	MONTHLY_OR_QUARTERLY,
	alpha,
	amount_fields,
	box,
	envelope,
	identification,
	page,
	period_dates,
	set_box,
)

PERIODS = MONTHLY_OR_QUARTERLY
LABELS = {
	"01": "Número de perceptores",
	"02": "Base de las retenciones e ingresos a cuenta",
	"03": "Retenciones e ingresos a cuenta",
	"04": "Resultado de anteriores declaraciones (complementaria)",
	# Sin número de casilla en el modelo: [03] - [04].
	"RES": "Resultado a ingresar",
}
# Posición, longitud y tipo (C = contador, U = importe sin signo) en la página 01.
PAGE_01 = {
	"01": (109, 15, "C"),
	"02": (124, 17, "U"),
	"03": (141, 17, "U"),
	"04": (158, 17, "U"),
	"RES": (175, 17, "U"),
}


def compute(doc) -> tuple[dict, None]:
	start, end = period_dates(doc.fiscal_year, doc.period)
	entries = informative.withholding_entries(doc.company, start, end, "115")
	return {
		"01": len({(e.party_type, e.party) for e in entries}),
		"02": round(sum(flt(e.taxable_amount) for e in entries), 2),
		"03": round(sum(flt(e.withholding_amount) for e in entries), 2),
	}, None


def totals(doc) -> None:
	set_box(doc, "RES", box(doc, "03") - box(doc, "04"))
	doc.result = box(doc, "RES")


def build(doc) -> str:
	nif, name = identification(doc)
	page1 = page(
		500,
		[
			(1, "<T11501000>"),
			(13, (doc.declaration_type or "I")[0]),
			(14, alpha(nif, 9)),
			(23, alpha(name, 60)),
			(103, str(doc.fiscal_year)),
			(107, doc.period),
			*amount_fields(doc, PAGE_01),
			(192, "X" if box(doc, "04") else " "),
			(489, "</T11501000>"),
		],
	)
	return envelope("115", doc.fiscal_year, doc.period, [page1])
