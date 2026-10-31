# Registro Fiscal IVA: generación, anulación y reconstrucción (spec 06 §2 y §4).

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from erpnext_spain.es_impuestos.codes import TAX_TYPES
from erpnext_spain.es_iva.breakdown import vat_breakdown
from erpnext_spain.utils.gating import is_pgc_company

REGISTER = "ES Vat Register"
BOOKS = {"Sales Invoice": "Expedidas", "Purchase Invoice": "Recibidas"}
VAT_TYPES = (TAX_TYPES["IVA"], TAX_TYPES["RE"])
NOT_DEDUCTIBLE = "No deducible"
ALLOWED_ROLES = ("Accounts Manager", "System Manager")


# --- doc_events ------------------------------------------------------------------


def on_submit(doc, method=None) -> None:
	if not is_pgc_company(doc.company):
		return
	rows = create_rows(doc)
	if any(row.unclassified for row in rows):
		frappe.msgprint(
			_(
				"Algunas filas de impuestos de {0} no tienen clasificación fiscal y quedan marcadas"
				" «Sin clasificar» en el Registro Fiscal IVA. Clasifíquelas en la plantilla de impuestos"
				" y reconstruya el registro."
			).format(frappe.bold(doc.name)),
			indicator="orange",
			alert=True,
		)


def on_cancel(doc, method=None) -> None:
	if not is_pgc_company(doc.company):
		return
	for name in frappe.get_all(
		REGISTER, filters={"voucher_type": doc.doctype, "voucher_no": doc.name}, pluck="name"
	):
		frappe.db.set_value(REGISTER, name, "cancelled", 1, update_modified=False)


# --- construcción de filas -------------------------------------------------------


def create_rows(doc) -> list:
	header = header_values(doc)
	pro_rata = company_pro_rata(doc.company) if doc.doctype == "Purchase Invoice" else 0
	sign = -1 if doc.get("is_return") else 1
	rows = []
	for part in vat_breakdown(doc):
		amount = part["tax_amount"]
		base = part["taxable_base"]
		if part["self_assessed"]:
			# La fila autorrepercutida se resta en la factura (Deduct): en el
			# registro es cuota devengada, en positivo salvo en rectificativas.
			amount, base = sign * abs(amount), sign * abs(base)
		deductible = 0.0
		applied = 0.0
		if doc.doctype == "Purchase Invoice" and part["tax_type"] in VAT_TYPES and not part["self_assessed"]:
			if part["deductibility"] != NOT_DEDUCTIBLE:
				applied = pro_rata
				deductible = flt(amount * pro_rata / 100, 2)
		row = frappe.get_doc(
			{
				"doctype": REGISTER,
				**header,
				"tax_row": part["tax_row"],
				"account": part["account"],
				"tax_type": part["tax_type"],
				"vat_classification": part["vat_classification"],
				"operation_type": part["operation_type"],
				"regime_key": part["regime_key"],
				"deductibility": part["deductibility"],
				"withholding_key": part["withholding_key"],
				"taxable_base": base,
				"tax_rate": part["tax_rate"],
				"tax_amount": amount,
				"deductible_amount": deductible,
				"pro_rata": applied,
				"self_assessed": part["self_assessed"],
				"unclassified": part["unclassified"],
			}
		)
		row.flags.ignore_permissions = True
		row.insert()
		rows.append(row)
	return rows


def header_values(doc) -> dict:
	purchase = doc.doctype == "Purchase Invoice"
	posting = getdate(doc.posting_date)
	party_type = "Supplier" if purchase else "Customer"
	party = doc.supplier if purchase else doc.customer
	country = party_country(doc, purchase)
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
		"id_type": identification_type(country),
		"country": country,
		"invoice_type": invoice_type(doc),
		"series": series,
		"number": number,
		"supplier_invoice_no": doc.get("bill_no") if purchase else None,
		"rectified_invoice": doc.get("return_against") or doc.get("es_external_rectified_number"),
		"invoice_total": flt(doc.get("base_grand_total")),
	}


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


def party_country(doc, purchase: bool) -> str | None:
	address = doc.get("supplier_address" if purchase else "customer_address")
	if address:
		country = frappe.get_cached_value("Address", address, "country")
		if country:
			return country
	from erpnext_spain.es_iva.eu import country_from_vat_id

	country = country_from_vat_id(doc.get("tax_id"))
	if country:
		return country
	return "Spain"


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


# --- reconstrucción ----------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def rebuild_vat_register(company: str, dry_run: bool = True) -> dict:
	"""Rehace el registro de las facturas de la compañía (spec 06 §4).

	Con dry_run solo cuenta; si no, encola el trabajo en la cola larga."""
	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Solo un usuario con rol Accounts Manager puede reconstruir el registro."),
			frappe.PermissionError,
		)
	frappe.get_doc("Company", company).check_permission("write")
	if not is_pgc_company(company):
		frappe.throw(_("La compañía {0} no tiene el plan PGC aplicado.").format(frappe.bold(company)))

	summary = {"invoices": 0, "cancelled": 0, "rows": 0, "unclassified": 0}
	for doctype in BOOKS:
		summary["invoices"] += frappe.db.count(doctype, {"company": company, "docstatus": 1})
		summary["cancelled"] += frappe.db.count(doctype, {"company": company, "docstatus": 2})
	summary["rows"] = frappe.db.count(REGISTER, {"company": company, "cancelled": 0})
	summary["unclassified"] = frappe.db.count(
		REGISTER, {"company": company, "cancelled": 0, "unclassified": 1}
	)
	if cint(dry_run):
		return summary

	frappe.enqueue(
		"erpnext_spain.es_iva.register.rebuild",
		queue="long",
		timeout=3600,
		company=company,
		user=frappe.session.user,
		enqueue_after_commit=True,
	)
	summary["queued"] = True
	return summary


def rebuild(company: str, user: str | None = None) -> dict:
	"""Sustituye las filas de cada factura validada y marca anuladas las de las
	canceladas. No modifica las facturas."""
	counts = {"invoices": 0, "rows": 0}
	for doctype in BOOKS:
		for name in frappe.get_all(doctype, filters={"company": company, "docstatus": 1}, pluck="name"):
			frappe.db.delete(REGISTER, {"voucher_type": doctype, "voucher_no": name})
			counts["rows"] += len(create_rows(frappe.get_doc(doctype, name)))
			counts["invoices"] += 1
		for name in frappe.get_all(doctype, filters={"company": company, "docstatus": 2}, pluck="name"):
			frappe.db.set_value(
				REGISTER, {"voucher_type": doctype, "voucher_no": name}, "cancelled", 1, update_modified=False
			)
	if user:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"document_type": "Company",
				"document_name": company,
				"subject": _("Registro Fiscal IVA de {0} reconstruido: {1} facturas, {2} filas.").format(
					company, counts["invoices"], counts["rows"]
				),
			}
		).insert(ignore_permissions=True)
	return counts
