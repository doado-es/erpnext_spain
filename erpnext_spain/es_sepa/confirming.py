# Confirming en el formato estándar de la AEF (v.03.26) (spec 12).
#
# Fichero de registros de 250 posiciones en ASCII: 1 cabecera, 2 domicilio del
# ordenante (opcional), por cada proveedor 3 (datos), 4 (email y teléfono) y 5
# (forma de pago), un 6 por factura o abono, y 7 totales. Alfanuméricos a la
# izquierda con espacios; numéricos a la derecha con ceros; fechas AAAAMMDD;
# importes con dos decimales implícitos.

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from erpnext_spain.es_sepa.credit_transfer import attach, check_role, company_address, company_tax_id
from erpnext_spain.es_sepa.utils import clean_iban, country_code, is_valid_iban, party_address, sepa_text
from erpnext_spain.utils.gating import is_pgc_company

RECORD_LENGTH = 250
CONFIRMING_MODE = "Confirming"
OPTION_A = "A - Sin reclasificar"
OPTION_B = "B - Reclasificar la deuda"


def alpha(value, length: int) -> str:
	text = (value or "").translate(
		str.maketrans("ÁÉÍÓÚÀÈÌÒÙÄËÏÖÜÑÇáéíóúàèìòùäëïöüñç", "AEIOUAEIOUAEIOUNCaeiouaeiouaeiounc")
	)
	text = "".join(char if 32 <= ord(char) < 127 else " " for char in text)
	return text[:length].ljust(length)


def numeric(value: int, length: int) -> str:
	return str(int(value)).rjust(length, "0")[-length:]


def cents(value: float) -> int:
	return round(abs(flt(value)) * 100)


def fecha(value) -> str:
	return getdate(value).strftime("%Y%m%d") if value else " " * 8


def record(*fields: str) -> str:
	line = "".join(fields)
	if len(line) > RECORD_LENGTH:
		frappe.throw(
			_("Registro de confirming de {0} posiciones (máximo {1}).").format(len(line), RECORD_LENGTH)
		)
	return line.ljust(RECORD_LENGTH)


def supplier_data(supplier: str) -> dict:
	doc = frappe.get_cached_doc("Supplier", supplier)
	address = party_address("Supplier", supplier) or {}
	bank = frappe.db.get_value(
		"Bank Account",
		{"party_type": "Supplier", "party": supplier, "is_default": 1},
		["iban", "bank"],
		as_dict=True,
	) or frappe.db.get_value(
		"Bank Account", {"party_type": "Supplier", "party": supplier}, ["iban", "bank"], as_dict=True
	)
	email = doc.get("email_id")
	if not email and doc.get("supplier_primary_contact"):
		email = frappe.get_cached_value("Contact", doc.supplier_primary_contact, "email_id")
	return {
		"name": doc.supplier_name,
		"tax_id": doc.tax_id,
		"address": address,
		"email": email,
		"phone": doc.get("mobile_no"),
		"iban": clean_iban(bank.iban) if bank else None,
		"bic": frappe.get_cached_value("Bank", bank.bank, "swift_number") if bank and bank.bank else None,
	}


def supplier_problems(data: dict) -> list[str]:
	problems = []
	address = data["address"]
	national = (address.get("country") or "Spain") == "Spain"
	for value, label in (
		(data["tax_id"], _("NIF")),
		(address.get("address_line1"), _("domicilio")),
		(address.get("city"), _("población")),
		(address.get("country"), _("país")),
		(data["email"], _("email")),
	):
		if not value:
			problems.append(label)
	if national and not address.get("pincode"):
		problems.append(_("código postal"))
	if not is_valid_iban(data["iban"]):
		problems.append(_("IBAN"))
	return problems


def build_file(batch) -> bytes:
	contract = contract_of(batch)
	company_name = frappe.get_cached_value("Company", batch.company, "company_name")
	iban = frappe.get_cached_value("Bank Account", batch.bank_account, "iban") or ""
	lines = [
		record(
			"1",
			alpha(company_name, 50),
			alpha(company_tax_id(batch.company), 15),
			" " * 8,
			fecha(batch.remittance_date),
			alpha(contract.contract_number, 20),
			alpha(clean_iban(iban), 34),
			alpha("EUR", 3),
			numeric(cint((batch.remittance_type or "1")[0]), 1),
			alpha(batch.name, 30),
			"FU",
		)
	]
	address = company_address(batch.company)
	if address:
		lines.append(
			record(
				"2",
				alpha(address.get("address_line1"), 65),
				alpha(address.get("city"), 40),
				alpha(address.get("pincode"), 10),
			)
		)
	by_supplier: dict[str, list] = {}
	for line in batch.lines:
		by_supplier.setdefault(line.supplier, []).append(line)
	total = 0
	for supplier, rows in by_supplier.items():
		data = supplier_data(supplier)
		address = data["address"]
		lines.append(
			record(
				"3",
				alpha(data["name"], 70),
				alpha(data["tax_id"], 20),
				alpha(address.get("address_line1"), 65),
				alpha(address.get("city"), 40),
				alpha(address.get("pincode"), 10),
				alpha(country_code(address.get("country")), 2),
			)
		)
		lines.append(record("4", alpha(data["email"], 50), alpha("", 50), alpha(data["phone"], 15)))
		lines.append(record("5", "T", alpha(data["iban"], 34), alpha(data["bic"], 11)))
		for row in rows:
			total += cents(row.amount) * (-1 if flt(row.amount) < 0 else 1)
			lines.append(
				record(
					"6",
					alpha(row.bill_no or row.purchase_invoice, 20),
					"-" if flt(row.amount) < 0 else "+",
					numeric(cents(row.amount), 15),
					fecha(row.bill_date),
					fecha(row.due_date),
					" " * 8,
					alpha(row.payment_reference, 16),
				)
			)
	lines.append(record("7", numeric(len(by_supplier), 12), numeric(abs(total), 15)))
	return ("\r\n".join(lines) + "\r\n").encode("ascii")


def contract_of(batch):
	"""Datos del contrato de confirming: la norma «Confirming» de la cuenta de cargo."""
	from erpnext_spain.es_sepa.bank_account import CONFIRMING, norm

	return norm(batch.bank_account, CONFIRMING)


# --- remesa ----------------------------------------------------------------------------


@frappe.whitelist()
def get_invoices(
	company: str, from_due_date: str | None = None, to_due_date: str | None = None
) -> list[dict]:
	"""Facturas de compra pendientes con modo de pago «Confirming» y los abonos
	pendientes de los mismos proveedores (con importe negativo)."""
	frappe.has_permission("Purchase Invoice", "read", throw=True)
	invoices = frappe.get_all(
		"Purchase Invoice",
		filters={"company": company, "docstatus": 1, "outstanding_amount": ["!=", 0]},
		fields=[
			"name",
			"supplier",
			"bill_no",
			"bill_date",
			"posting_date",
			"due_date",
			"outstanding_amount",
			"is_return",
		],
		order_by="supplier, due_date",
	)
	confirming = {
		row.parent
		for row in frappe.get_all(
			"Payment Schedule",
			filters={"parenttype": "Purchase Invoice", "mode_of_payment": CONFIRMING_MODE},
			fields=["parent"],
		)
	}
	selected = [
		i
		for i in invoices
		if not i.is_return
		and i.name in confirming
		and (not from_due_date or getdate(i.due_date) >= getdate(from_due_date))
		and (not to_due_date or getdate(i.due_date) <= getdate(to_due_date))
	]
	suppliers = {i.supplier for i in selected}
	selected += [i for i in invoices if i.is_return and i.supplier in suppliers]
	return [
		{
			"purchase_invoice": i.name,
			"supplier": i.supplier,
			"bill_no": i.bill_no or i.name,
			"bill_date": i.bill_date or i.posting_date,
			"due_date": i.due_date,
			"amount": i.outstanding_amount,
		}
		for i in selected
	]


def validate_batch(doc) -> None:
	if not is_pgc_company(doc.company):
		frappe.throw(_("La compañía {0} no tiene el plan PGC aplicado.").format(frappe.bold(doc.company)))
	account = frappe.db.get_value(
		"Bank Account", doc.bank_account, ["company", "is_company_account"], as_dict=True
	)
	if not account or not account.is_company_account or account.company != doc.company:
		frappe.throw(
			_("La cuenta {0} no es una cuenta bancaria de la compañía.").format(frappe.bold(doc.bank_account))
		)
	contract = contract_of(doc)
	doc.remittance_type = doc.remittance_type or contract.remittance_type
	for line in doc.lines:
		invoice = frappe.db.get_value(
			"Purchase Invoice",
			line.purchase_invoice,
			[
				"supplier",
				"company",
				"docstatus",
				"outstanding_amount",
				"bill_no",
				"bill_date",
				"posting_date",
				"due_date",
				"is_return",
			],
			as_dict=True,
		)
		if not invoice or invoice.docstatus != 1 or invoice.company != doc.company:
			frappe.throw(
				_("Fila {0}: la factura {1} no está validada o es de otra compañía.").format(
					line.idx, line.purchase_invoice
				)
			)
		line.supplier = invoice.supplier
		line.bill_no = line.bill_no or invoice.bill_no or line.purchase_invoice
		line.bill_date = line.bill_date or invoice.bill_date or invoice.posting_date
		line.due_date = line.due_date or invoice.due_date
		if not invoice.is_return and getdate(line.due_date) < getdate(doc.remittance_date):
			frappe.throw(
				_(
					"Fila {0}: la factura {1} vence el {2}, antes de la fecha de la remesa. Quítela o cambie la fecha."
				).format(line.idx, line.purchase_invoice, frappe.utils.formatdate(line.due_date)),
				title=_("Vencimiento anterior a la remesa"),
			)
		if abs(flt(line.amount)) > abs(flt(invoice.outstanding_amount)) + 0.005:
			frappe.throw(_("Fila {0}: el importe supera el pendiente de la factura.").format(line.idx))
		line.payment_reference = line.payment_reference or f"{doc.name[-10:]}{line.idx:03d}"[-16:]
	doc.total_amount = sum(flt(line.amount) for line in doc.lines)
	if flt(contract.limit) and doc.total_amount > flt(contract.limit):
		frappe.throw(
			_("La remesa ({0}) supera el límite del contrato {1} ({2}).").format(
				doc.total_amount, contract.contract_number, contract.limit
			),
			title=_("Límite del contrato"),
		)


def submit_batch(doc) -> None:
	check_role()
	problems = []
	for supplier in dict.fromkeys(line.supplier for line in doc.lines):
		missing = supplier_problems(supplier_data(supplier))
		if missing:
			problems.append(f"{supplier} ({', '.join(missing)})")
	if problems:
		frappe.throw(
			_("Faltan datos obligatorios del formato de confirming en: {0}").format("; ".join(problems)),
			title=_("Datos de proveedores incompletos"),
		)
	content = build_file(doc)
	doc.db_set("confirming_file", attach(doc.doctype, doc.name, f"{doc.name}-AEF.txt", content))
	for line in doc.lines:
		line.db_set("status", "Generada")
	contract = contract_of(doc)
	if contract.accounting_option == OPTION_B:
		doc.db_set("remittance_entry", reclassify_debt(doc, contract))


def dimensions(company: str) -> dict:
	return {"cost_center": frappe.get_cached_value("Company", company, "cost_center")}


def reclassify_debt(doc, contract) -> str:
	"""Opción B: 400 (proveedor, por factura) a la cuenta de la entidad."""
	if not contract.debt_account:
		frappe.throw(
			_(
				"La norma de confirming de la cuenta {0} reclasifica la deuda pero no tiene cuenta de la entidad."
			).format(doc.bank_account)
		)
	entry = frappe.new_doc("Journal Entry")
	entry.update(
		{
			"company": doc.company,
			"posting_date": doc.remittance_date,
			"user_remark": _("Remesa de confirming {0}").format(doc.name),
		}
	)
	for line in doc.lines:
		credit_to = frappe.db.get_value("Purchase Invoice", line.purchase_invoice, "credit_to")
		amount = flt(line.amount)
		entry.append(
			"accounts",
			{
				**dimensions(doc.company),
				"account": credit_to,
				"party_type": "Supplier",
				"party": line.supplier,
				"debit_in_account_currency": amount if amount > 0 else 0,
				"credit_in_account_currency": -amount if amount < 0 else 0,
				"reference_type": "Purchase Invoice",
				"reference_name": line.purchase_invoice,
			},
		)
	entry.append(
		"accounts",
		{
			**dimensions(doc.company),
			"account": contract.debt_account,
			"credit_in_account_currency": doc.total_amount,
		},
	)
	entry.insert()
	entry.submit()
	return entry.name


@frappe.whitelist(methods=["POST"])
def register_maturity(batch: str, charge_date: str | None = None) -> list[str]:
	"""Cargo al vencimiento. Opción A: un pago por proveedor (facturas y abonos);
	opción B: asiento de la cuenta de la entidad al banco. Los pagos llevan la
	referencia de la remesa para casarlos con el extracto (spec 13)."""
	check_role()
	doc = frappe.get_doc("ES Confirming Batch", batch)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Valide la remesa antes de registrar el vencimiento."))
	if doc.maturity_registered:
		frappe.throw(_("El vencimiento de la remesa {0} ya está registrado.").format(batch))
	contract = contract_of(doc)
	ledger = frappe.get_cached_value("Bank Account", doc.bank_account, "account")
	charge_date = charge_date or nowdate()
	created = []
	if contract.accounting_option == OPTION_B:
		entry = frappe.new_doc("Journal Entry")
		entry.update(
			{
				"voucher_type": "Bank Entry",
				"company": doc.company,
				"posting_date": charge_date,
				"cheque_no": doc.name,
				"cheque_date": charge_date,
				"user_remark": _("Vencimiento de la remesa de confirming {0}").format(doc.name),
			}
		)
		entry.append(
			"accounts",
			{
				**dimensions(doc.company),
				"account": contract.debt_account,
				"debit_in_account_currency": doc.total_amount,
			},
		)
		entry.append(
			"accounts",
			{**dimensions(doc.company), "account": ledger, "credit_in_account_currency": doc.total_amount},
		)
		entry.insert()
		entry.submit()
		created.append(entry.name)
	else:
		by_supplier: dict[str, list] = {}
		for line in doc.lines:
			by_supplier.setdefault(line.supplier, []).append(line)
		for supplier, rows in by_supplier.items():
			created.append(supplier_payment(doc, supplier, rows, ledger, charge_date))
	for line in doc.lines:
		line.db_set("status", "Pagada")
	doc.db_set("maturity_registered", 1)
	return created


def supplier_payment(doc, supplier: str, rows: list, ledger: str, charge_date) -> str:
	total = sum(flt(row.amount) for row in rows)
	payable = frappe.db.get_value("Purchase Invoice", rows[0].purchase_invoice, "credit_to")
	payment = frappe.new_doc("Payment Entry")
	payment.update(
		{
			"payment_type": "Pay",
			"company": doc.company,
			"posting_date": charge_date,
			"party_type": "Supplier",
			"party": supplier,
			"paid_from": ledger,
			"paid_to": payable,
			"paid_amount": total,
			"received_amount": total,
			"reference_no": doc.name,
			"reference_date": charge_date,
			"es_end_to_end_id": doc.name,
			**(
				{"mode_of_payment": CONFIRMING_MODE}
				if frappe.db.exists("Mode of Payment", CONFIRMING_MODE)
				else {}
			),
		}
	)
	for row in rows:
		payment.append(
			"references",
			{
				"reference_doctype": "Purchase Invoice",
				"reference_name": row.purchase_invoice,
				"allocated_amount": flt(row.amount),
			},
		)
	payment.setup_party_account_field()
	payment.set_missing_values()
	payment.insert()
	payment.submit()
	return payment.name
