# Ficheros SEPA (spec 11 §4-§5): pain.001.001.09 (transferencias) y
# pain.008.001.08 (adeudos directos), las versiones ISO 20022 de 2019 de las
# guías EPC de 2025. Cada fichero se valida contra el XSD oficial antes de
# guardarlo (erpnext_spain/schemas/iso20022).

import functools
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from lxml import etree

from erpnext_spain.es_sepa.utils import clean_iban, country_code, sepa_text

PAIN_001 = "pain.001.001.09"
PAIN_008 = "pain.008.001.08"
PAIN_002 = "pain.002.001.10"
NOT_PROVIDED = "NOTPROVIDED"


@dataclass
class Party:
	name: str
	iban: str
	bic: str | None = None
	address: dict | None = None
	identifier: str | None = None  # presentador (NIF + sufijo) o identificador de acreedor


@dataclass
class Transaction:
	end_to_end_id: str
	amount: Decimal
	party: Party
	remittance: str
	mandate_id: str | None = None
	mandate_date: date | None = None
	sequence: str | None = None


@dataclass
class Batch:
	message_id: str
	initiating_party: Party
	account: Party
	requested_date: date
	transactions: list[Transaction] = field(default_factory=list)
	scheme: str | None = None  # CORE / B2B
	priority: str = "NORM"
	instant: bool = False


def amount(value) -> Decimal:
	return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@functools.cache
def schema(message: str) -> etree.XMLSchema:
	path = frappe.get_app_path("erpnext_spain", "schemas", "iso20022", f"{message}.xsd")
	return etree.XMLSchema(etree.parse(path))


def sub(parent, tag: str, text=None, **attrs):
	"""Hijo en el mismo espacio de nombres que el padre."""
	namespace = etree.QName(parent).namespace
	element = etree.SubElement(parent, f"{{{namespace}}}{tag}" if namespace else tag, **attrs)
	if text is not None:
		element.text = str(text)
	return element


def postal_address(parent, address: dict | None) -> None:
	if not address:
		return
	node = sub(parent, "PstlAdr")
	if address.get("address_line1"):
		sub(node, "StrtNm", sepa_text(address["address_line1"], 70))
	if address.get("pincode"):
		sub(node, "PstCd", sepa_text(address["pincode"], 16))
	if address.get("city"):
		sub(node, "TwnNm", sepa_text(address["city"], 35))
	if address.get("country"):
		sub(node, "Ctry", country_code(address["country"]))
	if address.get("address_line2"):
		sub(node, "AdrLine", sepa_text(address["address_line2"], 70))


def agent(parent, tag: str, bic: str | None) -> None:
	institution = sub(sub(parent, tag), "FinInstnId")
	if bic:
		sub(institution, "BICFI", bic.strip().upper())
	else:
		sub(sub(institution, "Othr"), "Id", NOT_PROVIDED)


def organisation_id(parent, identifier: str | None) -> None:
	if identifier:
		sub(sub(sub(sub(parent, "Id"), "OrgId"), "Othr"), "Id", identifier)


def group_header(root, batch: Batch, total: Decimal) -> None:
	header = sub(root, "GrpHdr")
	sub(header, "MsgId", batch.message_id[:35])
	sub(header, "CreDtTm", datetime.now().replace(microsecond=0).isoformat())
	sub(header, "NbOfTxs", len(batch.transactions))
	sub(header, "CtrlSum", total)
	initiating = sub(header, "InitgPty")
	sub(initiating, "Nm", sepa_text(batch.initiating_party.name, 70))
	organisation_id(initiating, batch.initiating_party.identifier)


def credit_transfer(batch: Batch) -> bytes:
	ns = f"urn:iso:std:iso:20022:tech:xsd:{PAIN_001}"
	root = etree.Element(f"{{{ns}}}Document", nsmap={None: ns})
	body = sub(root, "CstmrCdtTrfInitn")
	total = sum((t.amount for t in batch.transactions), Decimal("0.00"))
	group_header(body, batch, total)

	info = sub(body, "PmtInf")
	sub(info, "PmtInfId", f"{batch.message_id}-1"[:35])
	sub(info, "PmtMtd", "TRF")
	sub(info, "NbOfTxs", len(batch.transactions))
	sub(info, "CtrlSum", total)
	payment_type = sub(info, "PmtTpInf")
	sub(payment_type, "InstrPrty", batch.priority)
	sub(sub(payment_type, "SvcLvl"), "Cd", "SEPA")
	if batch.instant:
		sub(sub(payment_type, "LclInstrm"), "Cd", "INST")
	sub(sub(info, "ReqdExctnDt"), "Dt", batch.requested_date.isoformat())
	debtor = sub(info, "Dbtr")
	sub(debtor, "Nm", sepa_text(batch.account.name, 70))
	postal_address(debtor, batch.account.address)
	sub(sub(sub(info, "DbtrAcct"), "Id"), "IBAN", clean_iban(batch.account.iban))
	agent(info, "DbtrAgt", batch.account.bic)
	sub(info, "ChrgBr", "SLEV")

	for tx in batch.transactions:
		node = sub(info, "CdtTrfTxInf")
		sub(sub(node, "PmtId"), "EndToEndId", tx.end_to_end_id[:35])
		sub(sub(node, "Amt"), "InstdAmt", tx.amount, Ccy="EUR")
		if tx.party.bic:
			agent(node, "CdtrAgt", tx.party.bic)
		creditor = sub(node, "Cdtr")
		sub(creditor, "Nm", sepa_text(tx.party.name, 70))
		postal_address(creditor, tx.party.address)
		sub(sub(sub(node, "CdtrAcct"), "Id"), "IBAN", clean_iban(tx.party.iban))
		sub(sub(node, "RmtInf"), "Ustrd", sepa_text(tx.remittance, 140))
	return validate_and_serialise(root, PAIN_001)


def direct_debit(batch: Batch) -> bytes:
	ns = f"urn:iso:std:iso:20022:tech:xsd:{PAIN_008}"
	root = etree.Element(f"{{{ns}}}Document", nsmap={None: ns})
	body = sub(root, "CstmrDrctDbtInitn")
	total = sum((t.amount for t in batch.transactions), Decimal("0.00"))
	group_header(body, batch, total)

	by_sequence: dict[str, list[Transaction]] = {}
	for tx in batch.transactions:
		by_sequence.setdefault(tx.sequence or "RCUR", []).append(tx)

	for index, (sequence, transactions) in enumerate(by_sequence.items(), 1):
		info = sub(body, "PmtInf")
		subtotal = sum((t.amount for t in transactions), Decimal("0.00"))
		sub(info, "PmtInfId", f"{batch.message_id}-{index}"[:35])
		sub(info, "PmtMtd", "DD")
		sub(info, "NbOfTxs", len(transactions))
		sub(info, "CtrlSum", subtotal)
		payment_type = sub(info, "PmtTpInf")
		sub(sub(payment_type, "SvcLvl"), "Cd", "SEPA")
		sub(sub(payment_type, "LclInstrm"), "Cd", batch.scheme or "CORE")
		sub(payment_type, "SeqTp", sequence)
		sub(info, "ReqdColltnDt", batch.requested_date.isoformat())
		creditor = sub(info, "Cdtr")
		sub(creditor, "Nm", sepa_text(batch.account.name, 70))
		postal_address(creditor, batch.account.address)
		sub(sub(sub(info, "CdtrAcct"), "Id"), "IBAN", clean_iban(batch.account.iban))
		agent(info, "CdtrAgt", batch.account.bic)
		sub(info, "ChrgBr", "SLEV")
		scheme = sub(sub(sub(info, "CdtrSchmeId"), "Id"), "PrvtId")
		other = sub(scheme, "Othr")
		sub(other, "Id", batch.account.identifier)
		sub(sub(other, "SchmeNm"), "Prtry", "SEPA")

		for tx in transactions:
			node = sub(info, "DrctDbtTxInf")
			sub(sub(node, "PmtId"), "EndToEndId", tx.end_to_end_id[:35])
			sub(node, "InstdAmt", tx.amount, Ccy="EUR")
			mandate = sub(sub(node, "DrctDbtTx"), "MndtRltdInf")
			sub(mandate, "MndtId", tx.mandate_id[:35])
			sub(mandate, "DtOfSgntr", tx.mandate_date.isoformat())
			agent(node, "DbtrAgt", tx.party.bic)
			debtor = sub(node, "Dbtr")
			sub(debtor, "Nm", sepa_text(tx.party.name, 70))
			postal_address(debtor, tx.party.address)
			sub(sub(sub(node, "DbtrAcct"), "Id"), "IBAN", clean_iban(tx.party.iban))
			sub(sub(node, "RmtInf"), "Ustrd", sepa_text(tx.remittance, 140))
	return validate_and_serialise(root, PAIN_008)


def validate_and_serialise(root, message: str) -> bytes:
	xsd = schema(message)
	if not xsd.validate(root):
		errors = "; ".join(f"{e.path}: {e.message}" for e in list(xsd.error_log)[:5])
		frappe.throw(
			_("El fichero {0} no cumple el esquema oficial: {1}").format(message, errors),
			title=_("Fichero SEPA no válido"),
		)
	return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# --- pain.002: informe de estado ----------------------------------------------------


def parse_status_report(content: bytes) -> dict:
	"""Estado del fichero y de cada operación de un pain.002 (cualquier versión).

	Devuelve {"group_status": ..., "transactions": {EndToEndId: (estado, motivo)}}."""
	try:
		root = etree.fromstring(content)
	except etree.XMLSyntaxError as error:
		frappe.throw(_("El fichero no es un XML válido: {0}").format(frappe.utils.escape_html(str(error))))
	namespace = etree.QName(root).namespace or ""
	if "pain.002" not in namespace:
		frappe.throw(
			_("El fichero no es un informe de estado pain.002 (espacio de nombres {0}).").format(namespace)
		)
	ns = {"p": namespace}
	group_status = root.findtext(".//p:OrgnlGrpInfAndSts/p:GrpSts", namespaces=ns)
	transactions = {}
	for tx in root.iterfind(".//p:TxInfAndSts", namespaces=ns):
		end_to_end = tx.findtext("p:OrgnlEndToEndId", namespaces=ns)
		status = tx.findtext("p:TxSts", namespaces=ns)
		reason = tx.findtext("p:StsRsnInf/p:Rsn/p:Cd", namespaces=ns) or tx.findtext(
			"p:StsRsnInf/p:Rsn/p:Prtry", namespaces=ns
		)
		if end_to_end:
			transactions[end_to_end] = (status, reason)
	return {"group_status": group_status, "transactions": transactions}
