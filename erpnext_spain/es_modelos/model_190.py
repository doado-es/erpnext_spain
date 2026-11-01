# Modelo 190: resumen anual de retenciones sobre rendimientos del trabajo y de
# actividades económicas (el anual del 111). Diseño de registro del ejercicio 2025
# (Orden HAC/1431/2025): registros de 500 posiciones. Revisar cuando la AEAT
# publique el del ejercicio 2026.
#
# Solo los perceptores que salen de las facturas de compra con retención
# (profesionales, administradores, cursos, actividades agrícolas...). Las nóminas
# (clave A) y los datos personales y familiares no se generan aquí.

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_spain.es_modelos import informative as inf
from erpnext_spain.es_modelos.returns import ANNUAL, box, period_dates, set_box

PERIODS = ANNUAL
LABELS = {
	"PER": "Número total de percepciones",
	"IMP": "Importe total de las percepciones",
	"RET": "Importe total de las retenciones e ingresos a cuenta",
}
# Claves con subclave obligatoria.
WITH_SUBKEY = set("BCEFGHIKL")


def compute(doc) -> tuple[dict, list[dict]]:
	start, end = period_dates(doc.fiscal_year, "0A")
	grouped: dict[tuple, dict] = {}
	for entry in inf.withholding_entries(doc.company, start, end, "111"):
		key = (entry.party_type, entry.party, entry.key_190 or "", entry.subkey_190 or "")
		line = grouped.setdefault(
			key,
			{
				"party_type": entry.party_type,
				"party": entry.party,
				"tax_id": entry.tax_id or frappe.get_cached_value(entry.party_type, entry.party, "tax_id"),
				"party_name": party_name(entry.party_type, entry.party),
				"province_code": inf.province_code(entry.party_type, entry.party),
				"operation_key": key[2],
				"subkey": key[3],
				"amount": 0.0,
				"withheld": 0.0,
			},
		)
		line["amount"] += flt(entry.taxable_amount)
		line["withheld"] += flt(entry.withholding_amount)
	lines = []
	for line in grouped.values():
		line["amount"], line["withheld"] = round(line["amount"], 2), round(line["withheld"], 2)
		notes = []
		if not line["operation_key"]:
			notes.append(_("La categoría de retención no tiene clave del 190."))
		elif line["operation_key"] in WITH_SUBKEY and not line["subkey"]:
			notes.append(_("La clave {0} necesita subclave.").format(line["operation_key"]))
		if not line["province_code"]:
			notes.append(_("Sin dirección en España: indique el código de provincia."))
		if notes:
			line["note"] = " ".join(notes)
		lines.append(line)
	return {}, lines


def party_name(party_type: str, party: str) -> str:
	field = "supplier_name" if party_type == "Supplier" else "customer_name"
	return frappe.get_cached_value(party_type, party, field) or party


def totals(doc) -> None:
	set_box(doc, "PER", len(doc.lines))
	set_box(doc, "IMP", sum(flt(line.amount) for line in doc.lines))
	set_box(doc, "RET", sum(flt(line.withheld) for line in doc.lines))
	doc.result = box(doc, "RET")


def build(doc) -> str:
	header = inf.record(
		[
			*inf.declarant_record(doc, "190"),
			(136, inf.num(box(doc, "PER"), 9)),
			(145, inf.signed_cents(box(doc, "IMP"), 16)),
			(161, inf.cents(box(doc, "RET"), 15)),
			(176, inf.an(doc.contact_email, 50, extra="@_")),
		]
	)
	return inf.as_file([header, *[perceptor(doc, line) for line in doc.lines]])


def perceptor(doc, line) -> str:
	if not line.operation_key:
		frappe.throw(_("Fila {0}: falta la clave de percepción de {1}.").format(line.idx, line.party_name))
	if line.operation_key in WITH_SUBKEY and not line.subkey:
		frappe.throw(_("Fila {0}: la clave {1} necesita subclave.").format(line.idx, line.operation_key))
	if not line.province_code:
		frappe.throw(_("Fila {0}: falta el código de provincia de {1}.").format(line.idx, line.party_name))
	return inf.record(
		[
			*inf.declarant_head(doc, "190", "2"),
			(18, inf.nif(line.tax_id)),
			(36, inf.an(line.party_name, 40)),
			(76, inf.num(line.province_code, 2)),
			(78, line.operation_key),
			(79, inf.num(line.subkey, 2) if line.subkey else "  "),
			# Percepciones dinerarias no derivadas de incapacidad laboral.
			(81, inf.signed_cents(line.amount, 14)),
			(95, inf.cents(line.withheld, 13)),
			# En especie: sin importes.
			(109, "0" * 39),
			(148, inf.num(line.accrual_year or 0, 4)),
			(152, "0"),
			# Datos adicionales (solo nóminas y pensiones): vacíos.
			(153, "0000"),
			(157, "0"),
			(167, "0000"),
			(171, "0" * 84),
			(256, "0" * 26),
			(283, "0" * 39),
			(322, "0"),
			(323, "0" * 65),
			(388, "00"),
			(390, "00000"),
		]
	)
