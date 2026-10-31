# Factura electrónica UBL 2.1 según EN 16931 (spec 10 §1-§2, B2B).
#
# - Emisión: se construye desde la Sales Invoice validada y el desglose fiscal
#   común (es_iva.breakdown, el mismo del Registro Fiscal IVA y de VeriFactu): no
#   se recalculan importes.
# - Validación: XSD oficial de OASIS (erpnext_spain/schemas/oasis/ubl21) y las
#   reglas aritméticas principales de EN 16931 (BR-CO-10, 13, 15 y 16 y la cuota
#   de cada categoría). Las reglas Schematron completas (XSLT 2.0) y la CIUS
#   española de la AEAT quedan pendientes **[revisar]**.
# - Recepción: lectura de un UBL de proveedor a una estructura simple.

import functools
import os
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import flt, getdate
from lxml import etree

from erpnext_spain.es_impuestos.codes import TAX_TYPES
from erpnext_spain.utils.company import legal_name

NS = {
	"Invoice": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
	"CreditNote": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
	"cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
	"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
CUSTOMIZATION = "urn:cen.eu:en16931:2017"
# Categoría de IVA (UNCL5305) por calificación fiscal (spec 03).
CATEGORY = {
	"S1": "S",
	"S2": "AE",
	"N1": "O",
	"N2": "O",
	"E1": "E",
	"E2": "G",
	"E3": "E",
	"E4": "E",
	"E5": "K",
	"E6": "E",
}
EXEMPTION_TEXT = {
	"AE": "Inversión del sujeto pasivo",
	"K": "Entrega intracomunitaria exenta (art. 25 Ley 37/1992)",
	"G": "Exportación exenta (art. 21 Ley 37/1992)",
	"E": "Operación exenta",
	"O": "Operación no sujeta",
}
VAT = TAX_TYPES["IVA"]
SURCHARGE = TAX_TYPES["RE"]
WITHHOLDING = TAX_TYPES["IRPF"]


class UblError(frappe.ValidationError):
	pass


def dec(value) -> Decimal:
	return Decimal(str(flt(value, 2))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def text(value) -> str:
	return f"{dec(value):.2f}"


# --- emisión -------------------------------------------------------------------------


@dataclass
class UblParty:
	name: str
	tax_id: str
	street: str = ""
	city: str = ""
	postcode: str = ""
	province: str = ""
	country: str = "ES"


@dataclass
class UblTax:
	category: str
	rate: Decimal
	base: Decimal
	amount: Decimal


@dataclass
class UblLine:
	number: int
	description: str
	quantity: Decimal
	net: Decimal
	price: Decimal
	category: str
	rate: Decimal


@dataclass
class UblInvoice:
	number: str
	issue_date: str
	due_date: str | None
	credit_note: bool
	currency: str
	seller: UblParty
	buyer: UblParty
	lines: list[UblLine]
	taxes: list[UblTax]
	withheld: Decimal
	iban: str | None
	references: list[tuple[str, str]] = field(default_factory=list)  # factura rectificada (número, fecha)


def address(name: str | None) -> dict:
	if not name:
		return {}
	return (
		frappe.get_cached_value(
			"Address", name, ["address_line1", "city", "pincode", "state", "country"], as_dict=True
		)
		or {}
	)


def party(name: str, tax_id: str, address_name: str | None) -> UblParty:
	from erpnext_spain.es_sepa.utils import country_code

	data = address(address_name)
	return UblParty(
		name=name,
		tax_id=tax_id or "",
		street=data.get("address_line1") or "",
		city=data.get("city") or "",
		postcode=data.get("pincode") or "",
		province=data.get("state") or "",
		country=country_code(data.get("country")) or "ES",
	)


def company_address_name(company: str) -> str | None:
	links = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Company", "link_name": company, "parenttype": "Address"},
		pluck="parent",
		limit=1,
	)
	return links[0] if links else None


def build(si) -> UblInvoice:
	from erpnext_spain.es_iva.breakdown import vat_breakdown

	if si.docstatus != 1:
		frappe.throw(_("Solo se generan facturas electrónicas de facturas validadas."), UblError)
	if si.currency != "EUR":
		frappe.throw(
			_("La primera versión de la factura electrónica UBL solo admite facturas en euros."), UblError
		)
	tax_rows = {row.name: row for row in si.taxes}
	if any(not row.get("es_tax_type") for row in si.taxes):
		frappe.throw(_("La factura {0} tiene filas de impuestos sin clasificar.").format(si.name), UblError)

	parts = vat_breakdown(si)
	taxes = [
		UblTax(
			CATEGORY.get(p["vat_classification"] or "S1", "S"),
			Decimal(str(p["tax_rate"])),
			dec(p["taxable_base"]),
			dec(p["tax_amount"]),
		)
		for p in parts
		if p["tax_type"] == VAT
	]
	surcharge = sum((dec(p["tax_amount"]) for p in parts if p["tax_type"] == SURCHARGE), Decimal("0"))
	if surcharge:
		# EN 16931 no tiene recargo de equivalencia: se suma a la cuota de la
		# categoría S del mismo base **[revisar con la CIUS española]**.
		frappe.throw(_("La factura electrónica UBL aún no admite el recargo de equivalencia."), UblError)
	withheld = -sum((dec(p["tax_amount"]) for p in parts if p["tax_type"] == WITHHOLDING), Decimal("0"))

	vat_by_item: dict[str, tuple[str, Decimal]] = {}
	for detail in si.get("item_wise_tax_details") or []:
		row = tax_rows.get(detail.tax_row)
		if row and row.es_tax_type == VAT:
			vat_by_item[detail.item_row] = (
				CATEGORY.get(row.es_vat_classification or "S1", "S"),
				Decimal(str(flt(detail.rate))),
			)
	lines = []
	for item in si.items:
		category, rate = vat_by_item.get(item.name, ("S", Decimal("0")))
		qty = Decimal(str(abs(flt(item.qty)) or 1))
		net = dec(abs(flt(item.base_net_amount)))
		lines.append(
			UblLine(
				number=item.idx,
				description=(item.item_name or item.item_code or item.description or "")[:200],
				quantity=qty,
				net=net,
				price=(net / qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
				category=category,
				rate=rate,
			)
		)
	sign = -1 if si.is_return else 1
	taxes = [UblTax(t.category, t.rate, t.base * sign, t.amount * sign) for t in taxes]
	references = []
	if si.get("return_against"):
		references.append(
			(si.return_against, str(frappe.db.get_value("Sales Invoice", si.return_against, "posting_date")))
		)
	company_tax = frappe.get_cached_value("Company", si.company, "tax_id")
	from erpnext_spain.es_efactura.facturae import company_iban

	try:
		iban = company_iban(frappe.get_cached_doc("Company", si.company))
	except Exception:
		iban = None
	return UblInvoice(
		number=si.name,
		issue_date=str(getdate(si.posting_date)),
		due_date=str(getdate(si.due_date)) if si.get("due_date") and not si.is_return else None,
		credit_note=bool(si.is_return),
		currency=si.currency,
		seller=party(
			legal_name(si.company),
			company_tax,
			company_address_name(si.company),
		),
		buyer=party(
			si.customer_name,
			si.tax_id or frappe.get_cached_value("Customer", si.customer, "tax_id"),
			si.customer_address,
		),
		lines=lines,
		taxes=taxes,
		withheld=withheld * sign,
		iban=iban,
		references=references,
	)


def vat_id(tax_id: str, country: str) -> str:
	value = (tax_id or "").replace(" ", "").upper()
	return (
		value if value[:2].isalpha() and not value[:1].isdigit() and len(value) > 9 else f"{country}{value}"
	)


def sub(parent, tag: str, value=None, **attrs):
	prefix, name = tag.split(":")
	element = etree.SubElement(parent, f"{{{NS[prefix]}}}{name}", **attrs)
	if value is not None:
		element.text = str(value)
	return element


def render_party(parent, tag: str, data: UblParty) -> None:
	node = sub(sub(parent, tag), "cac:Party")
	sub(sub(node, "cac:PartyName"), "cbc:Name", data.name)
	postal = sub(node, "cac:PostalAddress")
	if data.street:
		sub(postal, "cbc:StreetName", data.street)
	if data.city:
		sub(postal, "cbc:CityName", data.city)
	if data.postcode:
		sub(postal, "cbc:PostalZone", data.postcode)
	if data.province:
		sub(postal, "cbc:CountrySubentity", data.province)
	sub(sub(postal, "cac:Country"), "cbc:IdentificationCode", data.country)
	tax = sub(node, "cac:PartyTaxScheme")
	sub(tax, "cbc:CompanyID", vat_id(data.tax_id, data.country))
	sub(sub(tax, "cac:TaxScheme"), "cbc:ID", "VAT")
	legal = sub(node, "cac:PartyLegalEntity")
	sub(legal, "cbc:RegistrationName", data.name)
	sub(legal, "cbc:CompanyID", data.tax_id)


def render(invoice: UblInvoice) -> bytes:
	doc_type = "CreditNote" if invoice.credit_note else "Invoice"
	root = etree.Element(
		f"{{{NS[doc_type]}}}{doc_type}", nsmap={None: NS[doc_type], "cac": NS["cac"], "cbc": NS["cbc"]}
	)
	sub(root, "cbc:CustomizationID", CUSTOMIZATION)
	sub(root, "cbc:ID", invoice.number)
	sub(root, "cbc:IssueDate", invoice.issue_date)
	if invoice.due_date and not invoice.credit_note:
		sub(root, "cbc:DueDate", invoice.due_date)
	sub(
		root,
		"cbc:CreditNoteTypeCode" if invoice.credit_note else "cbc:InvoiceTypeCode",
		"381" if invoice.credit_note else "380",
	)
	sub(root, "cbc:DocumentCurrencyCode", invoice.currency)
	for number, date in invoice.references:
		reference = sub(sub(root, "cac:BillingReference"), "cac:InvoiceDocumentReference")
		sub(reference, "cbc:ID", number)
		sub(reference, "cbc:IssueDate", date)
	render_party(root, "cac:AccountingSupplierParty", invoice.seller)
	render_party(root, "cac:AccountingCustomerParty", invoice.buyer)
	if invoice.iban:
		means = sub(root, "cac:PaymentMeans")
		sub(means, "cbc:PaymentMeansCode", "58")
		sub(sub(means, "cac:PayeeFinancialAccount"), "cbc:ID", invoice.iban)

	currency = {"currencyID": invoice.currency}
	# Los importes ya vienen en positivo también en los abonos (build los normaliza).
	sign = Decimal("1")
	tax_total = sum((t.amount for t in invoice.taxes), Decimal("0")) * sign
	total = sub(root, "cac:TaxTotal")
	sub(total, "cbc:TaxAmount", text(tax_total), **currency)
	for tax in invoice.taxes:
		subtotal = sub(total, "cac:TaxSubtotal")
		sub(subtotal, "cbc:TaxableAmount", text(tax.base * sign), **currency)
		sub(subtotal, "cbc:TaxAmount", text(tax.amount * sign), **currency)
		category = sub(subtotal, "cac:TaxCategory")
		sub(category, "cbc:ID", tax.category)
		sub(category, "cbc:Percent", f"{tax.rate:.2f}")
		if tax.category != "S":
			sub(category, "cbc:TaxExemptionReason", EXEMPTION_TEXT.get(tax.category, ""))
		sub(sub(category, "cac:TaxScheme"), "cbc:ID", "VAT")
	if invoice.withheld:
		# Retención de IRPF: elemento WithholdingTaxTotal de UBL 2.1 **[revisar con la CIUS española]**.
		withholding = sub(root, "cac:WithholdingTaxTotal")
		sub(withholding, "cbc:TaxAmount", text(invoice.withheld * sign), **currency)

	lines_total = sum((line.net for line in invoice.lines), Decimal("0"))
	monetary = sub(root, "cac:LegalMonetaryTotal")
	sub(monetary, "cbc:LineExtensionAmount", text(lines_total), **currency)
	sub(monetary, "cbc:TaxExclusiveAmount", text(lines_total), **currency)
	sub(monetary, "cbc:TaxInclusiveAmount", text(lines_total + tax_total), **currency)
	if invoice.withheld:
		sub(monetary, "cbc:PrepaidAmount", text(invoice.withheld * sign), **currency)
	sub(monetary, "cbc:PayableAmount", text(lines_total + tax_total - invoice.withheld * sign), **currency)

	for line in invoice.lines:
		node = sub(root, "cac:CreditNoteLine" if invoice.credit_note else "cac:InvoiceLine")
		sub(node, "cbc:ID", line.number)
		sub(
			node,
			"cbc:CreditedQuantity" if invoice.credit_note else "cbc:InvoicedQuantity",
			f"{line.quantity:f}",
			unitCode="C62",
		)
		sub(node, "cbc:LineExtensionAmount", text(line.net), **currency)
		item = sub(node, "cac:Item")
		sub(item, "cbc:Name", line.description)
		category = sub(item, "cac:ClassifiedTaxCategory")
		sub(category, "cbc:ID", line.category)
		sub(category, "cbc:Percent", f"{line.rate:.2f}")
		sub(sub(category, "cac:TaxScheme"), "cbc:ID", "VAT")
		sub(sub(node, "cac:Price"), "cbc:PriceAmount", text(line.price), **currency)
	content = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
	validate(content)
	return content


# --- validación ------------------------------------------------------------------------


@functools.cache
def schema(doc_type: str) -> etree.XMLSchema:
	path = os.path.join(
		frappe.get_app_path("erpnext_spain", "schemas", "oasis", "ubl21", "maindoc"),
		f"UBL-{doc_type}-2.1.xsd",
	)
	return etree.XMLSchema(etree.parse(path))


def validate(content: bytes) -> None:
	root = etree.fromstring(content)
	doc_type = etree.QName(root).localname
	xsd = schema(doc_type)
	if not xsd.validate(root):
		errors = "; ".join(e.message for e in list(xsd.error_log)[:5])
		frappe.throw(_("La factura UBL no cumple el esquema UBL 2.1: {0}").format(errors), UblError)
	errors = business_rules(root)
	if errors:
		frappe.throw(_("La factura UBL no cumple EN 16931: {0}").format("; ".join(errors)), UblError)


def amount(root, path: str) -> Decimal:
	value = root.findtext(path, namespaces=NS)
	return Decimal(value) if value else Decimal("0")


def business_rules(root) -> list[str]:
	"""Reglas aritméticas principales de EN 16931."""
	errors = []
	credit = etree.QName(root).localname == "CreditNote"
	line_tag = "cac:CreditNoteLine" if credit else "cac:InvoiceLine"
	lines = sum(
		(amount(line, "cbc:LineExtensionAmount") for line in root.findall(line_tag, NS)), Decimal("0")
	)
	monetary = root.find("cac:LegalMonetaryTotal", NS)
	if lines != amount(monetary, "cbc:LineExtensionAmount"):
		errors.append("BR-CO-10: la suma de las líneas no coincide con el importe neto")
	if amount(monetary, "cbc:TaxExclusiveAmount") != amount(monetary, "cbc:LineExtensionAmount"):
		errors.append("BR-CO-13: el importe sin impuestos no coincide con las líneas")
	tax = amount(root, "cac:TaxTotal/cbc:TaxAmount")
	if amount(monetary, "cbc:TaxInclusiveAmount") != amount(monetary, "cbc:TaxExclusiveAmount") + tax:
		errors.append("BR-CO-15: el total con impuestos no es el neto más la cuota")
	if amount(monetary, "cbc:PayableAmount") != amount(monetary, "cbc:TaxInclusiveAmount") - amount(
		monetary, "cbc:PrepaidAmount"
	):
		errors.append("BR-CO-16: el importe a pagar no cuadra")
	subtotals = sum(
		(amount(s, "cbc:TaxAmount") for s in root.findall("cac:TaxTotal/cac:TaxSubtotal", NS)), Decimal("0")
	)
	if subtotals != tax:
		errors.append("BR-CO-14: la cuota total no es la suma de las categorías")
	for subtotal in root.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
		base, quota = amount(subtotal, "cbc:TaxableAmount"), amount(subtotal, "cbc:TaxAmount")
		rate = amount(subtotal, "cac:TaxCategory/cbc:Percent")
		if abs(base * rate / 100 - quota) > Decimal("0.01"):
			errors.append(f"BR-S-09: la cuota de la categoría al {rate} % no es base × tipo")
	for party in ("cac:AccountingSupplierParty", "cac:AccountingCustomerParty"):
		if not root.findtext(f"{party}/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", namespaces=NS):
			errors.append(f"BR-CO-09: falta el NIF-IVA de {party}")
	return errors


# --- recepción --------------------------------------------------------------------------


@dataclass
class ReceivedInvoice:
	number: str
	issue_date: str
	due_date: str | None
	credit_note: bool
	seller_name: str
	seller_tax_id: str
	buyer_tax_id: str
	lines: list[dict]
	taxes: list[dict]
	total: Decimal
	payable: Decimal


def parse(content: bytes) -> ReceivedInvoice:
	try:
		root = etree.fromstring(content)
	except etree.XMLSyntaxError as error:
		frappe.throw(
			_("El fichero no es un XML válido: {0}").format(frappe.utils.escape_html(str(error))), UblError
		)
	doc_type = etree.QName(root).localname
	if doc_type not in ("Invoice", "CreditNote"):
		frappe.throw(_("El fichero no es una factura UBL (elemento raíz {0}).").format(doc_type), UblError)
	validate(content)
	credit = doc_type == "CreditNote"

	def tax_id(party: str) -> str:
		value = root.findtext(
			f"{party}/cac:Party/cac:PartyLegalEntity/cbc:CompanyID", namespaces=NS
		) or root.findtext(f"{party}/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", namespaces=NS)
		value = (value or "").replace(" ", "").upper()
		return value[2:] if value.startswith("ES") else value

	lines = []
	for line in root.findall("cac:CreditNoteLine" if credit else "cac:InvoiceLine", NS):
		quantity = Decimal(
			line.findtext("cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity", namespaces=NS) or "1"
		)
		lines.append(
			{
				"description": line.findtext("cac:Item/cbc:Name", namespaces=NS) or "",
				"qty": float(quantity),
				"amount": float(amount(line, "cbc:LineExtensionAmount")),
				"rate": float(amount(line, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent")),
				"category": line.findtext("cac:Item/cac:ClassifiedTaxCategory/cbc:ID", namespaces=NS),
			}
		)
	taxes = [
		{
			"category": s.findtext("cac:TaxCategory/cbc:ID", namespaces=NS),
			"rate": float(amount(s, "cac:TaxCategory/cbc:Percent")),
			"base": float(amount(s, "cbc:TaxableAmount")),
			"amount": float(amount(s, "cbc:TaxAmount")),
		}
		for s in root.findall("cac:TaxTotal/cac:TaxSubtotal", NS)
	]
	monetary = root.find("cac:LegalMonetaryTotal", NS)
	return ReceivedInvoice(
		number=root.findtext("cbc:ID", namespaces=NS),
		issue_date=root.findtext("cbc:IssueDate", namespaces=NS),
		due_date=root.findtext("cbc:DueDate", namespaces=NS),
		credit_note=credit,
		seller_name=root.findtext(
			"cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name", namespaces=NS
		)
		or "",
		seller_tax_id=tax_id("cac:AccountingSupplierParty"),
		buyer_tax_id=tax_id("cac:AccountingCustomerParty"),
		lines=lines,
		taxes=taxes,
		total=amount(monetary, "cbc:TaxInclusiveAmount"),
		payable=amount(monetary, "cbc:PayableAmount"),
	)
