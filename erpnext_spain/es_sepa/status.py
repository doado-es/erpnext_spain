# Informes de estado pain.002 y devoluciones de adeudos (spec 11 §6).

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from erpnext_spain.es_sepa import xml
from erpnext_spain.es_sepa.credit_transfer import check_role

REJECTED = "RJCT"


def read_file(file_url: str) -> bytes:
	file = frappe.get_doc("File", {"file_url": file_url})
	file.check_permission("read")
	return file.get_content() if isinstance(file.get_content(), bytes) else file.get_content().encode()


def add_history(line, text: str) -> None:
	history = (line.history or "").strip()
	line.db_set("history", f"{history}\n{nowdate()}: {text}".strip())


@frappe.whitelist(methods=["POST"])
def import_direct_debit_status(batch: str, file_url: str) -> dict:
	"""Marca las operaciones rechazadas de una remesa y deshace su cobro, para que
	la factura quede pendiente (criterio 5)."""
	check_role()
	doc = frappe.get_doc("ES Sepa Direct Debit Batch", batch)
	doc.check_permission("write")
	report = xml.parse_status_report(read_file(file_url))
	counts = {"accepted": 0, "rejected": 0}
	for line in doc.lines:
		status, reason = report["transactions"].get(line.end_to_end_id, (report["group_status"], None))
		if status == REJECTED:
			undo_collection(line)
			line.db_set({"status": "Rechazada", "reason_code": reason})
			add_history(line, _("Rechazada por el banco ({0})").format(reason or "-"))
			counts["rejected"] += 1
		elif status:
			add_history(line, _("Estado del banco: {0}").format(status))
			counts["accepted"] += 1
	doc.db_set("status_report", file_url)
	return counts


def undo_collection(line) -> None:
	if not line.payment_entry:
		return
	payment = frappe.get_doc("Payment Entry", line.payment_entry)
	if payment.docstatus == 1:
		payment.flags.ignore_permissions = True
		# La remesa enlaza el cobro; ese enlace no debe impedir deshacerlo.
		payment.flags.ignore_links = True
		payment.cancel()
	elif payment.docstatus == 0:
		frappe.delete_doc("Payment Entry", payment.name, ignore_permissions=True)
		line.db_set("payment_entry", None)


@frappe.whitelist(methods=["POST"])
def register_return(batch: str, line_name: str, reason_code: str | None = None, charges: float = 0) -> dict:
	"""Devolución de un adeudo ya cobrado: deshace el cobro (la factura vuelve a
	estar pendiente) y anota los gastos de devolución en la 6260 (criterio 6)."""
	check_role()
	doc = frappe.get_doc("ES Sepa Direct Debit Batch", batch)
	doc.check_permission("write")
	line = next((row for row in doc.lines if row.name == line_name), None)
	if not line:
		frappe.throw(_("La línea {0} no es de la remesa {1}.").format(line_name, batch))
	if line.status in ("Rechazada", "Devuelta"):
		frappe.throw(
			_("El adeudo de la factura {0} ya está {1}.").format(line.sales_invoice, line.status.lower())
		)
	undo_collection(line)
	result = {"charges_entry": None}
	if flt(charges) > 0:
		result["charges_entry"] = charges_entry(doc, line, flt(charges))
	line.db_set({"status": "Devuelta", "reason_code": reason_code})
	add_history(line, _("Devuelta ({0}); gastos {1}").format(reason_code or "-", flt(charges)))
	return result


def charges_entry(doc, line, charges: float) -> str:
	from erpnext_spain.es_contabilidad.pgc import account_by_number

	bank_ledger = frappe.get_cached_value("Bank Account", doc.bank_account, "account")
	cost_center = frappe.get_cached_value("Company", doc.company, "cost_center")
	entry = frappe.new_doc("Journal Entry")
	entry.update(
		{
			"voucher_type": "Bank Entry",
			"company": doc.company,
			"posting_date": nowdate(),
			"cheque_no": line.end_to_end_id,
			"cheque_date": nowdate(),
			"user_remark": _("Gastos de devolución del adeudo de la factura {0}").format(line.sales_invoice),
		}
	)
	# Gastos de devolución a la 6260 (servicios bancarios) **[revisar: 626 o 669]**.
	entry.append(
		"accounts",
		{
			"account": account_by_number(doc.company, "6260"),
			"debit_in_account_currency": charges,
			"cost_center": cost_center,
		},
	)
	entry.append(
		"accounts",
		{"account": bank_ledger, "credit_in_account_currency": charges, "cost_center": cost_center},
	)
	entry.insert()
	entry.submit()
	return entry.name
