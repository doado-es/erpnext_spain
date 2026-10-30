# Generación de facturas Facturae (spec 10 §1): modelo interno → XML 3.2.2.
#
# Los importes se toman de la factura validada (líneas, filas de impuesto y
# desglose nativo item_wise_tax_details de v16) sin recalcular nada; lo único que
# se calcula son los totales de Facturae, y antes de generar se comprueba que
# cuadran al céntimo con los de la factura.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import flt, getdate, strip_html

from erpnext_spain.es_efactura import codes
from erpnext_spain.es_impuestos.codes import VAT_CLASSIFICATIONS
from erpnext_spain.nif import validator

CENT = Decimal("0.01")
VAT, IRPF = "01", "04"
SPAIN = "ES"

LEGAL_LITERALS = {
	"S2": "Operación con inversión del sujeto pasivo (art. 84.Uno.2.º de la Ley 37/1992 del IVA).",
	"E1": "Operación exenta del IVA (art. 20 de la Ley 37/1992).",
	"E2": "Exportación exenta del IVA (art. 21 de la Ley 37/1992).",
	"E5": "Entrega intracomunitaria exenta del IVA (art. 25 de la Ley 37/1992).",
	"N2": "Operación no sujeta al IVA por las reglas de localización.",
}


class FacturaeError(frappe.ValidationError):
	pass


def fail(message: str) -> None:
	frappe.throw(message, FacturaeError, title=_("Factura electrónica"))


def money(value) -> Decimal:
	return Decimal(str(flt(value))).quantize(CENT, rounding=ROUND_HALF_UP)


def two(value) -> str:
	return f"{money(value):.2f}"


def eight(value) -> str:
	text = f"{Decimal(str(value)):.8f}".rstrip("0").rstrip(".")
	return text if text not in ("", "-0") else "0"


# --- modelo interno -----------------------------------------------------------


@dataclass
class Address:
	address: str
	postcode: str
	town: str
	province: str
	country: str  # alfa-3
	in_spain: bool


@dataclass
class Party:
	tax_id: str
	person_type: str  # F / J
	residence: str  # R / U / E
	name: str
	address: Address
	first_name: str | None = None
	first_surname: str | None = None
	second_surname: str | None = None
	centres: list[tuple[str, str, str]] = field(default_factory=list)  # (rol, código, descripción)


@dataclass
class TaxLine:
	code: str
	rate: Decimal
	base: Decimal
	amount: Decimal
	surcharge_rate: Decimal | None = None
	surcharge_amount: Decimal | None = None


@dataclass
class Line:
	description: str
	quantity: float
	unit: str
	total: Decimal
	taxes: list[TaxLine]
	withheld: list[TaxLine]
	special_event: tuple[str, str] | None = None


@dataclass
class Installment:
	due_date: str
	amount: Decimal
	means: str
	iban: str | None


@dataclass
class Corrective:
	number: str
	issue_date: str
	reason_code: str
	method: str
	explanation: str


@dataclass
class InvoiceModel:
	number: str
	issue_date: str
	document_type: str  # FC / FA
	currency: str
	seller: Party
	buyer: Party
	lines: list[Line]
	taxes: list[TaxLine]
	withheld: list[TaxLine]
	gross: Decimal
	total_taxes: Decimal
	total_withheld: Decimal
	total: Decimal
	installments: list[Installment]
	literals: list[str]
	corrective: Corrective | None = None


# --- construcción desde Sales Invoice ----------------------------------------


def build_model(si) -> InvoiceModel:
	if si.docstatus != 1:
		fail(_("Solo se pueden generar facturas electrónicas de facturas validadas."))
	if si.currency != "EUR":
		fail(
			_(
				"La factura {0} está en {1}; la primera versión de Facturae solo admite facturas en euros."
			).format(si.name, si.currency)
		)
	if flt(si.rounding_adjustment):
		fail(
			_(
				"La factura {0} tiene un ajuste por redondeo del total ({1}), que Facturae no admite."
				" Desactive el redondeo del total («Disable Rounded Total») en la factura o en la configuración contable."
			).format(si.name, si.rounding_adjustment)
		)
	if len(si.name) > 20:
		fail(
			_(
				"El número de factura {0} tiene más de 20 caracteres, el máximo de Facturae. Use una serie más corta."
			).format(si.name)
		)

	company = frappe.get_cached_doc("Company", si.company)
	customer = frappe.get_cached_doc("Customer", si.customer)
	seller = company_party(company)
	buyer = customer_party(customer, si.customer_address, company=company)

	tax_rows = {row.name: row for row in si.taxes}
	for row in si.taxes:
		if not row.get("es_tax_type"):
			fail(
				_(
					"La fila {0} de impuestos ({1}) no tiene tipo de impuesto (clasificación fiscal). Use una plantilla"
					" de impuestos de la app o complete la clasificación en la fila."
				).format(row.idx, row.description)
			)

	details: dict[str, list] = {}
	for detail in si.get("item_wise_tax_details") or []:
		details.setdefault(detail.item_row, []).append(detail)

	lines = []
	literals = []
	for item in si.items:
		taxes, withheld, special = line_taxes(item, details.get(item.name, []), tax_rows)
		if special and special[0] in LEGAL_LITERALS and LEGAL_LITERALS[special[0]] not in literals:
			literals.append(LEGAL_LITERALS[special[0]])
		lines.append(
			Line(
				description=strip_html(item.description or item.item_name or item.item_code).strip()[:2500],
				quantity=flt(item.qty),
				unit=frappe.get_cached_value("UOM", item.uom, "es_facturae_unit") or codes.DEFAULT_UNIT,
				total=money(item.net_amount),
				taxes=taxes,
				withheld=withheld,
				special_event=(special[1], special[2]) if special and special[1] else None,
			)
		)

	taxes = aggregate([t for line in lines for t in line.taxes])
	withheld = aggregate([t for line in lines for t in line.withheld])
	gross = sum((line.total for line in lines), Decimal("0"))
	total_taxes = sum((t.amount + (t.surcharge_amount or 0) for t in taxes), Decimal("0"))
	total_withheld = sum((t.amount for t in withheld), Decimal("0"))
	total = gross + total_taxes - total_withheld

	check_totals(si, gross, total_taxes, total_withheld, total)

	model = InvoiceModel(
		number=si.name,
		issue_date=str(getdate(si.posting_date)),
		document_type="FA" if si.get("es_invoice_type") in ("F2", "R5") else "FC",
		currency=si.currency,
		seller=seller,
		buyer=buyer,
		lines=lines,
		taxes=taxes,
		withheld=withheld,
		gross=gross,
		total_taxes=total_taxes,
		total_withheld=total_withheld,
		total=total,
		installments=installments(si, company, total) if total > 0 else [],
		literals=literals,
	)
	if si.is_return:
		model.corrective = corrective(si)
	return model


def line_taxes(item, details, tax_rows):
	"""Impuestos de una línea desde item_wise_tax_details (base y cuota por fila)."""
	vat: list[TaxLine] = []
	surcharges: list = []
	withheld: list[TaxLine] = []
	special = None
	for detail in details:
		row = tax_rows.get(detail.tax_row)
		if not row:
			continue
		kind = row.es_tax_type
		rate = Decimal(str(flt(detail.rate)))
		base = money(detail.taxable_amount if detail.taxable_amount is not None else item.net_amount)
		amount = money(detail.amount)
		if kind == "IVA":
			vat.append(TaxLine(VAT, rate, base, amount))
			classification = row.get("es_vat_classification")
			if classification and classification.startswith(("E", "N")):
				# Exenta (01) o no sujeta (02): hecho imponible especial con su motivo.
				event = "02" if classification.startswith("N") else "01"
				special = (classification, event, VAT_CLASSIFICATIONS.get(classification, classification))
			elif classification == "S2":
				# La inversión del sujeto pasivo solo lleva mención legal.
				special = (classification, None, None)
		elif kind == "Recargo de equivalencia":
			surcharges.append((rate, amount))
		elif kind == "Retención IRPF":
			# La retención va con tipo negativo en la factura; Facturae la quiere en positivo.
			withheld.append(TaxLine(IRPF, abs(rate), base, -amount))
	if not vat:
		fail(
			_(
				"La línea {0} ({1}) no tiene IVA. Facturae exige un impuesto en cada línea; si la operación está exenta o"
				" no sujeta, use la plantilla correspondiente (tipo 0 con su calificación)."
			).format(item.idx, item.item_code)
		)
	if surcharges:
		rate, amount = surcharges[0]
		vat[0].surcharge_rate, vat[0].surcharge_amount = rate, amount
	return vat, withheld, special


def aggregate(taxes: list[TaxLine]) -> list[TaxLine]:
	groups: dict[tuple, TaxLine] = {}
	for tax in taxes:
		key = (tax.code, tax.rate, tax.surcharge_rate)
		if key not in groups:
			groups[key] = TaxLine(
				tax.code,
				tax.rate,
				Decimal("0"),
				Decimal("0"),
				tax.surcharge_rate,
				Decimal("0") if tax.surcharge_rate is not None else None,
			)
		group = groups[key]
		group.base += tax.base
		group.amount += tax.amount
		if tax.surcharge_amount is not None:
			group.surcharge_amount = (group.surcharge_amount or Decimal("0")) + tax.surcharge_amount
	return list(groups.values())


def check_totals(si, gross, total_taxes, total_withheld, total) -> None:
	"""Los totales de Facturae deben coincidir al céntimo con los de la factura."""
	expected_withheld = sum(
		(
			-money(row.base_tax_amount_after_discount_amount)
			for row in si.taxes
			if row.es_tax_type == "Retención IRPF"
		),
		Decimal("0"),
	)
	expected_taxes = sum(
		(
			money(row.base_tax_amount_after_discount_amount)
			for row in si.taxes
			if row.es_tax_type in ("IVA", "Recargo de equivalencia")
		),
		Decimal("0"),
	)
	checks = (
		(_("base imponible"), gross, money(si.net_total)),
		(_("impuestos repercutidos"), total_taxes, expected_taxes),
		(_("retenciones"), total_withheld, expected_withheld),
		(_("total"), total, money(si.grand_total)),
	)
	for label, got, expected in checks:
		if got != expected:
			fail(
				_(
					"Los importes de la factura {0} no cuadran para Facturae ({1}: {2} calculado por líneas frente a {3}"
					" en la factura). Suele deberse a descuentos o redondeos aplicados al total; revise la factura."
				).format(si.name, label, got, expected)
			)


def tax_id(value: str | None, who: str) -> str:
	value = (value or "").replace(" ", "").replace("-", "").upper()
	if value.startswith("ES") and len(value) > 9:
		value = value[2:]
	if len(value) < 3:
		fail(_("Falta el NIF de {0}. Facturae lo exige.").format(who))
	return value


def person_type(doc, nif: str, spanish: bool) -> str:
	if doc.get("es_person_type"):
		return codes.PERSON_TYPES[doc.es_person_type]
	if spanish:
		try:
			if validator.validate_spanish_tax_id(nif).kind in ("dni", "nie"):
				return "F"
		except validator.InvalidTaxID:
			fail(_("El NIF {0} de {1} no es válido.").format(nif, doc.name))
	return "J"


def address_of(name: str | None, who: str) -> Address:
	if not name:
		fail(_("Falta la dirección de {0}. Facturae exige dirección postal.").format(who))
	doc = frappe.get_cached_doc("Address", name)
	country_code = (frappe.get_cached_value("Country", doc.country, "code") or "").upper()
	alpha3 = codes.alpha3(country_code)
	if not alpha3:
		fail(
			_("El país «{0}» de la dirección de {1} no tiene código ISO válido para Facturae.").format(
				doc.country, who
			)
		)
	in_spain = country_code == SPAIN
	postcode = (doc.pincode or "").replace(" ", "")
	if in_spain and not re.fullmatch(r"\d{5}", postcode):
		fail(
			_("El código postal de la dirección de {0} ({1}) debe tener 5 dígitos.").format(
				who, postcode or "-"
			)
		)
	province = codes.province_for(postcode) if in_spain else (doc.state or doc.city or "")[:20]
	lines = " ".join(x for x in (doc.address_line1, doc.address_line2) if x)
	if not lines or not doc.city:
		fail(_("La dirección de {0} necesita calle y municipio.").format(who))
	return Address(lines[:80], postcode, doc.city[:50], (province or "")[:20], alpha3, in_spain)


def company_address(company) -> str | None:
	from frappe.contacts.doctype.address.address import get_company_address

	result = get_company_address(company.name)
	return result.company_address if result else None


def company_party(company) -> Party:
	nif = tax_id(company.tax_id, _("la compañía {0}").format(company.name))
	address = address_of(company_address(company), _("la compañía {0}").format(company.name))
	return make_party(company, nif, company.company_name, address, "R")


def customer_party(customer, address_name, company) -> Party:
	address = address_of(address_name, _("el cliente {0}").format(customer.name))
	country = address.country
	residence = "R" if address.in_spain else ("U" if alpha2_in_eu(country) else "E")
	nif = tax_id(customer.tax_id, _("el cliente {0}").format(customer.name))
	party = make_party(customer, nif, customer.customer_name, address, residence)
	if customer.get("es_public_administration"):
		for fieldname, (role, label) in codes.DIR3_ROLES.items():
			code = (customer.get(fieldname) or "").strip()
			if code:
				party.centres.append((role, code, label))
		if len(party.centres) < 3:
			fail(
				_(
					"El cliente {0} es una Administración Pública: complete los códigos DIR3 de oficina contable, órgano"
					" gestor y unidad tramitadora en su ficha (sección Factura electrónica)."
				).format(customer.name)
			)
	return party


def alpha2_in_eu(alpha3: str) -> bool:
	return any(codes.alpha3(code) == alpha3 for code in codes.EU_COUNTRIES)


def make_party(doc, nif: str, name: str, address: Address, residence: str) -> Party:
	kind = person_type(doc, nif, residence == "R")
	party = Party(tax_id=nif, person_type=kind, residence=residence, name=(name or "")[:80], address=address)
	if kind == "F":
		party.first_name = doc.get("es_individual_name")
		party.first_surname = doc.get("es_first_surname")
		party.second_surname = doc.get("es_second_surname")
		if not party.first_name or not party.first_surname:
			fail(
				_(
					"{0} es persona física: Facturae exige nombre y primer apellido por separado. Complételos en la"
					" sección Factura electrónica de su ficha."
				).format(doc.name)
			)
	return party


def installments(si, company, total: Decimal) -> list[Installment]:
	rows = si.get("payment_schedule") or []
	schedule = [(row.due_date, money(row.payment_amount), row.mode_of_payment) for row in rows] or [
		(si.due_date or si.posting_date, total, si.get("mode_of_payment"))
	]
	if sum((amount for _due, amount, _mode in schedule), Decimal("0")) != total:
		schedule = [(si.due_date or si.posting_date, total, schedule[0][2])]
	result = []
	iban = None
	for due, amount, mode in schedule:
		means = (
			mode and frappe.get_cached_value("Mode of Payment", mode, "es_facturae_payment_means")
		) or codes.DEFAULT_PAYMENT_MEANS
		if means in codes.MEANS_WITH_IBAN and means == "04":
			iban = iban or company_iban(company)
		result.append(Installment(str(getdate(due)), amount, means, iban if means == "04" else None))
	return result


def company_iban(company) -> str:
	filters = {"is_company_account": 1, "company": company.name, "disabled": 0}
	iban = frappe.db.get_value("Bank Account", {**filters, "is_default": 1}, "iban") or frappe.db.get_value(
		"Bank Account", filters, "iban"
	)
	if not iban:
		fail(
			_(
				"El pago por transferencia necesita el IBAN de la compañía {0}. Cree una cuenta bancaria de la empresa"
				" (Bank Account, «Is Company Account») con su IBAN."
			).format(company.name)
		)
	return iban.replace(" ", "").upper()


def corrective(si) -> Corrective:
	if not si.return_against:
		fail(
			_("La rectificativa {0} debe indicar la factura que rectifica («Return Against»).").format(
				si.name
			)
		)
	reason = si.get("es_rectification_reason_code")
	if not reason or not si.get("es_rectification_reason"):
		fail(
			_("La rectificativa {0} necesita el motivo y la explicación de la rectificación.").format(si.name)
		)
	original_date = frappe.db.get_value("Sales Invoice", si.return_against, "posting_date")
	return Corrective(
		number=si.return_against,
		issue_date=str(getdate(original_date)),
		reason_code=reason,
		method=si.get("es_correction_method") or "02",
		explanation=si.es_rectification_reason,
	)


# --- serialización Facturae 3.2.2 ---------------------------------------------


def render(model: InvoiceModel, version: str = codes.DEFAULT_VERSION):
	from lxml import etree

	ns = codes.NAMESPACES[version]
	root = etree.Element(f"{{{ns}}}Facturae", nsmap={"fe": ns, "ds": "http://www.w3.org/2000/09/xmldsig#"})

	def sub(parent, tag, text=None):
		element = etree.SubElement(parent, tag)
		if text is not None:
			element.text = str(text)
		return element

	def amount(parent, tag, value):
		sub(sub(parent, tag), "TotalAmount", two(value))

	header = sub(root, "FileHeader")
	sub(header, "SchemaVersion", version)
	sub(header, "Modality", "I")
	sub(header, "InvoiceIssuerType", "EM")
	batch = sub(header, "Batch")
	sub(batch, "BatchIdentifier", f"{model.seller.tax_id}{model.number}"[:70])
	sub(batch, "InvoicesCount", "1")
	amount(batch, "TotalInvoicesAmount", model.total)
	amount(batch, "TotalOutstandingAmount", model.total)
	amount(batch, "TotalExecutableAmount", model.total)
	sub(batch, "InvoiceCurrencyCode", model.currency)

	parties = sub(root, "Parties")
	render_party(sub(parties, "SellerParty"), model.seller, sub)
	render_party(sub(parties, "BuyerParty"), model.buyer, sub)

	invoice = sub(sub(root, "Invoices"), "Invoice")
	head = sub(invoice, "InvoiceHeader")
	sub(head, "InvoiceNumber", model.number)
	sub(head, "InvoiceDocumentType", model.document_type)
	sub(head, "InvoiceClass", "OR" if model.corrective else "OO")
	if model.corrective:
		corr = sub(head, "Corrective")
		sub(corr, "InvoiceNumber", model.corrective.number[:20])
		sub(corr, "ReasonCode", model.corrective.reason_code)
		sub(corr, "ReasonDescription", codes.REASONS[model.corrective.reason_code])
		period = sub(corr, "TaxPeriod")
		sub(period, "StartDate", model.corrective.issue_date)
		sub(period, "EndDate", model.corrective.issue_date)
		sub(corr, "CorrectionMethod", model.corrective.method)
		sub(corr, "CorrectionMethodDescription", codes.CORRECTION_METHODS[model.corrective.method])
		sub(corr, "AdditionalReasonDescription", model.corrective.explanation[:2500])
		sub(corr, "InvoiceIssueDate", model.corrective.issue_date)

	issue = sub(invoice, "InvoiceIssueData")
	sub(issue, "IssueDate", model.issue_date)
	sub(issue, "InvoiceCurrencyCode", model.currency)
	sub(issue, "TaxCurrencyCode", "EUR")
	sub(issue, "LanguageName", "es")

	outputs = sub(invoice, "TaxesOutputs")
	for tax in model.taxes:
		render_tax(sub(outputs, "Tax"), tax, sub, amount, output=True)
	if model.withheld:
		withheld = sub(invoice, "TaxesWithheld")
		for tax in model.withheld:
			render_tax(sub(withheld, "Tax"), tax, sub, amount, output=False)

	totals = sub(invoice, "InvoiceTotals")
	sub(totals, "TotalGrossAmount", two(model.gross))
	sub(totals, "TotalGrossAmountBeforeTaxes", two(model.gross))
	sub(totals, "TotalTaxOutputs", two(model.total_taxes))
	sub(totals, "TotalTaxesWithheld", two(model.total_withheld))
	sub(totals, "InvoiceTotal", two(model.total))
	sub(totals, "TotalOutstandingAmount", two(model.total))
	sub(totals, "TotalExecutableAmount", two(model.total))

	items = sub(invoice, "Items")
	for line in model.lines:
		row = sub(items, "InvoiceLine")
		sub(row, "ItemDescription", line.description)
		sub(row, "Quantity", eight(line.quantity))
		sub(row, "UnitOfMeasure", line.unit)
		unit_price = (line.total / Decimal(str(line.quantity))) if line.quantity else line.total
		sub(
			row,
			"UnitPriceWithoutTax",
			eight(unit_price.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)),
		)
		sub(row, "TotalCost", two(line.total))
		sub(row, "GrossAmount", two(line.total))
		if line.withheld:
			withheld = sub(row, "TaxesWithheld")
			for tax in line.withheld:
				render_tax(sub(withheld, "Tax"), tax, sub, amount, output=False)
		taxes = sub(row, "TaxesOutputs")
		for tax in line.taxes:
			render_tax(sub(taxes, "Tax"), tax, sub, amount, output=True)
		if line.special_event and line.special_event[0]:
			event = sub(row, "SpecialTaxableEvent")
			sub(event, "SpecialTaxableEventCode", line.special_event[0])
			sub(event, "SpecialTaxableEventReason", line.special_event[1])

	if model.installments:
		payments = sub(invoice, "PaymentDetails")
		for inst in model.installments:
			installment = sub(payments, "Installment")
			sub(installment, "InstallmentDueDate", inst.due_date)
			sub(installment, "InstallmentAmount", two(inst.amount))
			sub(installment, "PaymentMeans", inst.means)
			if inst.iban:
				sub(sub(installment, "AccountToBeCredited"), "IBAN", inst.iban)
	if model.literals:
		literals = sub(invoice, "LegalLiterals")
		for literal in model.literals:
			sub(literals, "LegalReference", literal[:250])
	return root


def render_party(parent, party: Party, sub) -> None:
	ident = sub(parent, "TaxIdentification")
	sub(ident, "PersonTypeCode", party.person_type)
	sub(ident, "ResidenceTypeCode", party.residence)
	sub(ident, "TaxIdentificationNumber", party.tax_id)
	if party.centres:
		centres = sub(parent, "AdministrativeCentres")
		for role, code, label in party.centres:
			centre = sub(centres, "AdministrativeCentre")
			sub(centre, "CentreCode", code[:10])
			sub(centre, "RoleTypeCode", role)
			render_address(centre, party.address, sub)
			sub(centre, "CentreDescription", label)
	if party.person_type == "F":
		person = sub(parent, "Individual")
		sub(person, "Name", party.first_name[:40])
		sub(person, "FirstSurname", party.first_surname[:40])
		if party.second_surname:
			sub(person, "SecondSurname", party.second_surname[:40])
	else:
		person = sub(parent, "LegalEntity")
		sub(person, "CorporateName", party.name)
	render_address(person, party.address, sub)


def render_address(parent, address: Address, sub) -> None:
	if address.in_spain:
		node = sub(parent, "AddressInSpain")
		sub(node, "Address", address.address)
		sub(node, "PostCode", address.postcode)
		sub(node, "Town", address.town)
		sub(node, "Province", address.province)
		sub(node, "CountryCode", address.country)
	else:
		node = sub(parent, "OverseasAddress")
		sub(node, "Address", address.address)
		sub(node, "PostCodeAndTown", f"{address.postcode} {address.town}".strip()[:50])
		sub(node, "Province", address.province or address.town[:20])
		sub(node, "CountryCode", address.country)


def render_tax(parent, tax: TaxLine, sub, amount, output: bool) -> None:
	sub(parent, "TaxTypeCode", tax.code)
	sub(parent, "TaxRate", two(tax.rate))
	amount(parent, "TaxableBase", tax.base)
	amount(parent, "TaxAmount", tax.amount)
	if output and tax.surcharge_rate is not None:
		sub(parent, "EquivalenceSurcharge", two(tax.surcharge_rate))
		amount(parent, "EquivalenceSurchargeAmount", tax.surcharge_amount or 0)


# --- validación contra el esquema oficial --------------------------------------


class LocalSchemaResolver:
	"""Resuelve el import de xmldsig-core-schema.xsd al fichero local: sin red."""

	def __new__(cls):
		from lxml import etree

		class _Resolver(etree.Resolver):
			def resolve(self, url, pubid, context):
				if url.endswith("xmldsig-core-schema.xsd"):
					return self.resolve_filename(str(codes.SCHEMA_DIR / "xmldsig-core-schema.xsd"), context)
				return None

		return _Resolver()


_SCHEMAS: dict = {}


def schema(version: str = codes.DEFAULT_VERSION):
	from lxml import etree

	if version not in _SCHEMAS:
		parser = etree.XMLParser(no_network=True, load_dtd=False, resolve_entities=True)
		parser.resolvers.add(LocalSchemaResolver())
		doc = etree.parse(str(codes.SCHEMA_FILES[version]), parser)
		_SCHEMAS[version] = etree.XMLSchema(doc)
	return _SCHEMAS[version]


def validate_xml(xml: bytes, version: str = codes.DEFAULT_VERSION) -> None:
	from lxml import etree

	document = etree.fromstring(xml, etree.XMLParser(no_network=True, resolve_entities=False))
	validator_ = schema(version)
	if not validator_.validate(document):
		errors = "; ".join(f"línea {e.line}: {e.message}" for e in list(validator_.error_log)[:5])
		fail(_("El XML generado no cumple el esquema Facturae {0}: {1}").format(version, errors))
