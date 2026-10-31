# Registros del SII (spec 14 §2-§3) a partir del Registro Fiscal IVA (spec 06).
#
# Se construyen como diccionarios con los nombres del esquema de la AEAT
# (SuministroLR.xsd / SuministroInformacion.xsd v1.1, en
# erpnext_spain/schemas/aeat/sii) y se validan renderizándolos con zeep contra el
# esquema oficial antes de guardarlos. Importes en euros con dos decimales;
# fechas dd-mm-aaaa.

import functools
import os
import re

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext_spain.es_impuestos.codes import TAX_TYPES

SII_VERSION = "1.1"
VAT = TAX_TYPES["IVA"]
SURCHARGE = TAX_TYPES["RE"]
ISSUED, RECEIVED = "Emitidas", "Recibidas"
NEW, CHANGE, CANCEL = "A0", "A1", "Baja"
OPERATIONS = {
	(ISSUED, NEW): ("SuministroLRFacturasEmitidas", "RegistroLRFacturasEmitidas"),
	(ISSUED, CHANGE): ("SuministroLRFacturasEmitidas", "RegistroLRFacturasEmitidas"),
	(ISSUED, CANCEL): ("AnulacionLRFacturasEmitidas", "RegistroLRBajaExpedidas"),
	(RECEIVED, NEW): ("SuministroLRFacturasRecibidas", "RegistroLRFacturasRecibidas"),
	(RECEIVED, CHANGE): ("SuministroLRFacturasRecibidas", "RegistroLRFacturasRecibidas"),
	(RECEIVED, CANCEL): ("AnulacionLRFacturasRecibidas", "RegistroLRBajaRecibidas"),
}
ELEMENTS = {
	"SuministroLRFacturasEmitidas": "SuministroLRFacturasEmitidas",
	"SuministroLRFacturasRecibidas": "SuministroLRFacturasRecibidas",
	"AnulacionLRFacturasEmitidas": "BajaLRFacturasEmitidas",
	"AnulacionLRFacturasRecibidas": "BajaLRFacturasRecibidas",
}
LR_NAMESPACE = "https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/aplicaciones/es/aeat/ssii/fact/ws/SuministroLR.xsd"
WSDL = {ISSUED: "SuministroFactEmitidas.wsdl", RECEIVED: "SuministroFactRecibidas.wsdl"}
# Clave de régimen por tipo de operación cuando la fila no la trae (spec 03).
REGIME_BY_OPERATION = {
	"Exportación": "02",
	"Adquisición intracomunitaria de bienes": "09",
	"Adquisición intracomunitaria de servicios": "09",
}


def money(value) -> str:
	return f"{flt(value, 2):.2f}"


def rate(value) -> str:
	return f"{flt(value, 2):.2f}"


def aeat_date(value) -> str:
	return getdate(value).strftime("%d-%m-%Y")


def clean_nif(value: str | None) -> str:
	nif = re.sub(r"[^0-9A-Za-z]", "", value or "").upper()
	return nif[2:] if nif.startswith("ES") and len(nif) == 11 else nif


def counterpart(row) -> dict:
	"""Contraparte: NIF español o IDOtro (país, tipo, número)."""
	name = (row.party_name or row.party or "")[:120]
	if not row.id_type:
		return {"NombreRazon": name, "NIF": clean_nif(row.tax_id)}
	from erpnext_spain.es_sepa.utils import country_code

	return {
		"NombreRazon": name,
		"IDOtro": {
			"CodigoPais": country_code(row.country) or None,
			"IDType": row.id_type,
			"ID": (row.tax_id or "")[:20],
		},
	}


def period(row) -> dict:
	return {"Ejercicio": str(row.fiscal_year), "Periodo": f"{int(row.month):02d}"}


def header(company: str, communication: str | None) -> dict:
	head = {
		"IDVersionSii": SII_VERSION,
		"Titular": {
			"NombreRazon": frappe.get_cached_value("Company", company, "company_name")[:120],
			"NIF": clean_nif(frappe.get_cached_value("Company", company, "tax_id")),
		},
	}
	if communication and communication != CANCEL:
		head["TipoComunicacion"] = communication
	return head


def register_rows(doctype: str, name: str) -> list:
	return frappe.get_all(
		"ES Vat Register",
		filters={"voucher_type": doctype, "voucher_no": name, "cancelled": 0},
		fields=["*"],
		order_by="tax_rate desc",
	)


def invoice_type(row) -> str:
	code = row.invoice_type or "F1"
	return code if re.match(r"^(F[1-6]|R[1-5]|LC)$", code) else "F1"


def rectification(doc, row) -> dict:
	if not invoice_type(row).startswith("R"):
		return {}
	return {"TipoRectificativa": "I"}


def regime_key(rows) -> str:
	"""Clave de régimen de la factura. El tipo de operación manda sobre el «01»
	general que llevan por defecto las plantillas (exportación 02, adquisiciones
	intracomunitarias 09)."""
	for row in rows:
		if row.operation_type in REGIME_BY_OPERATION and (row.regime_key or "01") == "01":
			return REGIME_BY_OPERATION[row.operation_type]
	for row in rows:
		if row.regime_key:
			return row.regime_key
	return "01"


# --- expedidas -----------------------------------------------------------------------


def issued_breakdown(rows) -> dict:
	exempt, not_exempt, not_subject = (
		[],
		{},
		{"ImportePorArticulos7_14_Otros": 0.0, "ImporteTAIReglasLocalizacion": 0.0},
	)
	for row in rows:
		classification = row.vat_classification or "S1"
		if row.tax_type == SURCHARGE:
			continue
		if classification.startswith("E"):
			exempt.append({"CausaExencion": classification, "BaseImponible": money(row.taxable_base)})
		elif classification == "N1":
			not_subject["ImportePorArticulos7_14_Otros"] += flt(row.taxable_base)
		elif classification == "N2":
			not_subject["ImporteTAIReglasLocalizacion"] += flt(row.taxable_base)
		else:
			detail = {
				"TipoImpositivo": rate(row.tax_rate),
				"BaseImponible": money(row.taxable_base),
				"CuotaRepercutida": money(row.tax_amount),
			}
			surcharge = next(
				(
					r
					for r in rows
					if r.tax_type == SURCHARGE and abs(flt(r.taxable_base) - flt(row.taxable_base)) < 0.01
				),
				None,
			)
			if surcharge:
				detail.update(
					TipoRecargoEquivalencia=rate(surcharge.tax_rate),
					CuotaRecargoEquivalencia=money(surcharge.tax_amount),
				)
			not_exempt.setdefault(classification, []).append(detail)
	result = {}
	subject = {}
	if exempt:
		subject["Exenta"] = {"DetalleExenta": exempt}
	if not_exempt:
		# El esquema admite un único TipoNoExenta por desglose: si hay S1 y S2 se
		# informa el primero **[revisar: usar DesgloseTipoOperacion]**.
		classification, details = next(iter(not_exempt.items()))
		subject["NoExenta"] = {"TipoNoExenta": classification, "DesgloseIVA": {"DetalleIVA": details}}
	if subject:
		result["Sujeta"] = subject
	if any(not_subject.values()):
		result["NoSujeta"] = {k: money(v) for k, v in not_subject.items() if v}
	return result


def issued_record(doc, rows) -> dict:
	first = rows[0]
	breakdown = issued_breakdown(rows)
	description = doc.get("remarks") if doc.get("remarks") not in (None, "", "No Remarks") else None
	invoice = {
		"TipoFactura": invoice_type(first),
		**rectification(doc, first),
		"ClaveRegimenEspecialOTrascendencia": regime_key(rows),
		"ImporteTotal": money(first.invoice_total),
		"DescripcionOperacion": (description or _("Venta de bienes o prestación de servicios"))[:500],
	}
	if first.id_type or first.tax_id:
		invoice["Contraparte"] = counterpart(first)
	# Con destinatario extranjero se desglosa por tipo de operación (entrega de bienes).
	if first.id_type:
		invoice["TipoDesglose"] = {"DesgloseTipoOperacion": {"Entrega": breakdown}}
	else:
		invoice["TipoDesglose"] = {"DesgloseFactura": breakdown}
	return {
		"PeriodoLiquidacion": period(first),
		"IDFactura": {
			"IDEmisorFactura": {"NIF": clean_nif(frappe.get_cached_value("Company", doc.company, "tax_id"))},
			"NumSerieFacturaEmisor": doc.name,
			"FechaExpedicionFacturaEmisor": aeat_date(first.issue_date),
		},
		"FacturaExpedida": invoice,
	}


# --- recibidas -----------------------------------------------------------------------


def received_record(doc, rows) -> dict:
	first = rows[0]
	reverse, ordinary = [], []
	deductible = 0.0
	for row in rows:
		if row.tax_type == SURCHARGE or row.self_assessed:
			continue
		deductible += flt(row.deductible_amount)
		detail = {
			"TipoImpositivo": rate(row.tax_rate),
			"BaseImponible": money(row.taxable_base),
			"CuotaSoportada": money(row.tax_amount),
		}
		# ISP (S2) en su bloque; las adquisiciones intracomunitarias van en el
		# desglose ordinario con la clave de régimen 09.
		is_reverse = row.vat_classification == "S2" and not (row.operation_type or "").startswith(
			"Adquisición intracomunitaria"
		)
		(reverse if is_reverse else ordinary).append(detail)
	breakdown = {}
	if reverse:
		breakdown["InversionSujetoPasivo"] = {"DetalleIVA": reverse}
	if ordinary:
		breakdown["DesgloseIVA"] = {"DetalleIVA": ordinary}
	if not breakdown:
		breakdown["DesgloseIVA"] = {
			"DetalleIVA": [{"BaseImponible": money(sum(flt(r.taxable_base) for r in rows))}]
		}
	party = counterpart(first)
	issuer = {"IDOtro": party["IDOtro"]} if "IDOtro" in party else {"NIF": party["NIF"]}
	return {
		"PeriodoLiquidacion": period(first),
		"IDFactura": {
			"IDEmisorFactura": issuer,
			"NumSerieFacturaEmisor": (first.supplier_invoice_no or doc.name)[:60],
			"FechaExpedicionFacturaEmisor": aeat_date(first.issue_date),
		},
		"FacturaRecibida": {
			"TipoFactura": invoice_type(first),
			**rectification(doc, first),
			"ClaveRegimenEspecialOTrascendencia": regime_key(rows),
			"ImporteTotal": money(first.invoice_total),
			"DescripcionOperacion": _("Compra de bienes o servicios"),
			"DesgloseFactura": breakdown,
			"Contraparte": party,
			"FechaRegContable": aeat_date(first.posting_date),
			"CuotaDeducible": money(deductible),
		},
	}


def cancellation_record(book: str, content: dict) -> dict:
	"""Baja: periodo e identificación de la factura del alta (y nombre del emisor en recibidas)."""
	if book == ISSUED:
		identification = content["IDFactura"]
	else:
		identification = dict(content["IDFactura"])
		emitter = dict(identification["IDEmisorFactura"])
		emitter = {"NombreRazon": content["FacturaRecibida"]["Contraparte"]["NombreRazon"], **emitter}
		identification["IDEmisorFactura"] = emitter
	return {"PeriodoLiquidacion": content["PeriodoLiquidacion"], "IDFactura": identification}


def build_record(doc) -> dict:
	rows = register_rows(doc.doctype, doc.name)
	if not rows:
		frappe.throw(_("La factura {0} no tiene filas en el Registro Fiscal IVA.").format(doc.name))
	record = issued_record(doc, rows) if doc.doctype == "Sales Invoice" else received_record(doc, rows)
	validate_records(doc.company, ISSUED if doc.doctype == "Sales Invoice" else RECEIVED, NEW, [record])
	return record


# --- validación contra el esquema ------------------------------------------------------


@functools.cache
def zeep_client(book: str):
	from erpnext_spain.aeat.client import load_wsdl_client

	return load_wsdl_client(
		os.path.join(frappe.get_app_path("erpnext_spain", "schemas", "aeat", "sii"), WSDL[book])
	)


@functools.cache
def lr_schema():
	from lxml import etree

	return etree.XMLSchema(
		etree.parse(
			os.path.join(frappe.get_app_path("erpnext_spain", "schemas", "aeat", "sii"), "SuministroLR.xsd")
		)
	)


def payload(company: str, book: str, communication: str, records: list[dict]) -> dict:
	operation, list_name = OPERATIONS[(book, communication)]
	return {"operacion": operation, "datos": {"Cabecera": header(company, communication), list_name: records}}


def validate_records(company: str, book: str, communication: str, records: list[dict]) -> None:
	"""Renderiza el mensaje con zeep y lo valida con el XSD oficial (criterio 2)."""
	from lxml import etree

	data = payload(company, book, communication, records)
	element = zeep_client(book).get_element(f"{{{LR_NAMESPACE}}}{ELEMENTS[data['operacion']]}")
	root = etree.Element("root")
	try:
		element.render(root, element(**data["datos"]))
	except (TypeError, ValueError) as error:
		frappe.throw(
			_("El registro del SII no tiene la estructura del esquema: {0}").format(error),
			title=_("Registro SII no válido"),
		)
	schema = lr_schema()
	if not schema.validate(root[0]):
		errors = "; ".join(e.message for e in list(schema.error_log)[:5])
		frappe.throw(
			_("El registro del SII no cumple el esquema de la AEAT: {0}").format(errors),
			title=_("Registro SII no válido"),
		)
