# Desglose fiscal de las facturas para libros, modelos y SII (spec 06).
#
# Sin tabla propia: las filas se calculan sobre la marcha desde la factura
# validada con la función común `breakdown.vat_breakdown`, como hace ERPNext con
# sus informes fiscales. Para que lo declarado no cambie con la configuración,
# la factura guarda al validar los únicos datos que no llevaba ya:
#
# - la clasificación de su Item Tax Template en cada línea,
# - el país y el tipo de identificación del tercero,
# - en compras, la prorrata aplicada.
#
# El NIF y el nombre del tercero, la clasificación de cada fila de impuestos y
# las bases y cuotas por artículo ya los guarda ERPNext en la propia factura.

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext_spain.es_impuestos.codes import TAX_TYPES
from erpnext_spain.es_iva.breakdown import vat_breakdown
from erpnext_spain.utils.gating import is_pgc_company

BOOKS = {"Sales Invoice": "Expedidas", "Purchase Invoice": "Recibidas"}
VAT_TYPES = (TAX_TYPES["IVA"], TAX_TYPES["RE"])
NOT_DEDUCTIBLE = "No deducible"


# --- congelación al validar ---------------------------------------------------------------


def validate(doc, method=None) -> None:
	"""Sales Invoice / Purchase Invoice: congela los datos del desglose."""
	if not is_pgc_company(doc.company):
		return
	freeze_item_classification(doc)
	if doc.docstatus == 1:
		country = party_country(doc)
		doc.es_party_country = country
		doc.es_id_type = identification_type(country)
		if doc.doctype == "Purchase Invoice":
			doc.es_pro_rata = company_pro_rata(doc.company)
		if any(row["unclassified"] for row in invoice_rows(doc)):
			frappe.msgprint(
				_(
					"Algunas filas de impuestos de {0} no tienen clasificación fiscal y salen como «sin"
					" clasificar» en los libros de IVA. Clasifíquelas en la plantilla de impuestos."
				).format(frappe.bold(doc.name)),
				indicator="orange",
				alert=True,
			)


def freeze_item_classification(doc) -> None:
	for item in doc.get("items") or []:
		values = None
		if item.get("item_tax_template"):
			values = frappe.get_cached_value(
				"Item Tax Template",
				item.item_tax_template,
				["es_vat_classification", "es_operation_type"],
				as_dict=True,
			)
		item.es_vat_classification = values.es_vat_classification if values else None
		item.es_operation_type = values.es_operation_type if values else None


def party_country(doc) -> str:
	purchase = doc.doctype == "Purchase Invoice"
	address = doc.get("supplier_address" if purchase else "customer_address")
	if address:
		country = frappe.get_cached_value("Address", address, "country")
		if country:
			return country
	from erpnext_spain.es_iva.eu import country_from_vat_id

	return country_from_vat_id(doc.get("tax_id")) or "Spain"


def identification_type(country: str | None) -> str:
	"""Clave de identificación del SII/VeriFactu: vacío (NIF español), 02 (NIF-IVA
	de la UE) o 06 (otro documento) **[revisar]**."""
	if not country or country == "Spain":
		return ""
	from erpnext_spain.es_iva.eu import is_eu_country

	return "02" if is_eu_country(country) else "06"


def company_pro_rata(company: str) -> float:
	value = flt(frappe.get_cached_value("Company", company, "es_vat_pro_rata"))
	return value if 0 < value <= 100 else 100.0


# --- filas del desglose ---------------------------------------------------------------------


def invoice_type(doc) -> str:
	if doc.get("es_invoice_type"):
		return doc.es_invoice_type
	# Facturas recibidas: el tipo lo decide el proveedor; R1 para las
	# rectificativas y F1 para el resto **[revisar con el SII, spec 14]**.
	return "R1" if doc.get("is_return") else "F1"


def split_name(name: str) -> tuple[str, str]:
	"""Serie y número de un nombre como «F-ABC-26-00012» → («F-ABC-26-», «00012»)."""
	head = name.rstrip("0123456789")
	return (head, name[len(head) :]) if head != name else ("", name)


def header(doc) -> dict:
	purchase = doc.doctype == "Purchase Invoice"
	posting = getdate(doc.posting_date)
	party_type = "Supplier" if purchase else "Customer"
	party = doc.supplier if purchase else doc.customer
	# Facturas anteriores a la congelación: se calcula con los datos actuales.
	country = doc.get("es_party_country") or party_country(doc)
	id_type = doc.get("es_id_type") if doc.get("es_party_country") else identification_type(country)
	series, number = split_name(doc.name)
	return {
		"company": doc.company,
		"book": BOOKS[doc.doctype],
		"voucher_type": doc.doctype,
		"voucher_no": doc.name,
		"posting_date": doc.posting_date,
		"issue_date": (doc.get("bill_date") or doc.posting_date) if purchase else doc.posting_date,
		"fiscal_year": posting.year,
		"quarter": f"{(posting.month - 1) // 3 + 1}T",
		"month": posting.month,
		"party_type": party_type,
		"party": party,
		"party_name": doc.get("supplier_name" if purchase else "customer_name") or party,
		"tax_id": doc.get("tax_id") or frappe.get_cached_value(party_type, party, "tax_id"),
		"id_type": id_type or "",
		"country": country,
		"invoice_type": invoice_type(doc),
		"series": series,
		"number": number,
		"supplier_invoice_no": doc.get("bill_no") if purchase else None,
		"rectified_invoice": doc.get("return_against") or doc.get("es_external_rectified_number"),
		"invoice_total": flt(doc.get("base_grand_total")),
	}


def invoice_rows(doc) -> list[frappe._dict]:
	"""Filas del desglose fiscal de una factura (lo que antes guardaba el Registro
	Fiscal IVA): una por fila de impuesto, calificación, tipo de operación y tipo."""
	head = header(doc)
	purchase = doc.doctype == "Purchase Invoice"
	pro_rata = (flt(doc.get("es_pro_rata")) or company_pro_rata(doc.company)) if purchase else 0
	sign = -1 if doc.get("is_return") else 1
	rows = []
	for part in vat_breakdown(doc):
		amount, base = part["tax_amount"], part["taxable_base"]
		if part["self_assessed"]:
			# La fila autorrepercutida se resta en la factura (Deduct): es cuota
			# devengada, en positivo salvo en rectificativas.
			amount, base = sign * abs(amount), sign * abs(base)
		deductible = applied = 0.0
		if (
			purchase
			and part["tax_type"] in VAT_TYPES
			and not part["self_assessed"]
			and part["deductibility"] != NOT_DEDUCTIBLE
		):
			applied = pro_rata
			deductible = flt(amount * pro_rata / 100, 2)
		rows.append(
			frappe._dict(
				head,
				tax_row=part["tax_row"],
				account=part["account"],
				tax_type=part["tax_type"],
				vat_classification=part["vat_classification"],
				operation_type=part["operation_type"],
				regime_key=part["regime_key"],
				deductibility=part["deductibility"],
				withholding_key=part["withholding_key"],
				taxable_base=base,
				tax_rate=part["tax_rate"],
				tax_amount=amount,
				deductible_amount=deductible,
				pro_rata=applied,
				self_assessed=part["self_assessed"],
				unclassified=part["unclassified"],
			)
		)
	return rows


def period_rows(
	company: str, from_date, to_date, book: str | None = None, tax_types=VAT_TYPES
) -> list[frappe._dict]:
	"""Filas de las facturas validadas de la compañía en el periodo (por fecha de
	contabilización). Las canceladas no cuentan."""
	rows = []
	for doctype, name_book in BOOKS.items():
		if book and book != name_book:
			continue
		for name in frappe.get_all(
			doctype,
			filters={"company": company, "docstatus": 1, "posting_date": ["between", [from_date, to_date]]},
			pluck="name",
			order_by="posting_date, name",
		):
			rows += [
				row
				for row in invoice_rows(frappe.get_doc(doctype, name))
				if not tax_types or row.tax_type in tax_types
			]
	return rows
