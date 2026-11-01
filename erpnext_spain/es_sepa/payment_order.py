# Órdenes de pago (Payment Order) por efectos: vencimientos de facturas de compra
# que se pagan por transferencia.
#
# «Añadir efectos» crea un Payment Entry en borrador por proveedor (y cuenta del
# proveedor en el plan), con una referencia por vencimiento, y lo añade a la
# orden. Los pagos se validan al validar la orden; mientras la orden es un
# borrador, quitar un pago de la tabla o borrar la orden borra sus borradores.
# Solo se tocan los pagos que creó este flujo (Payment Entry.payment_order).

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from erpnext_spain.es_sepa import effects
from erpnext_spain.es_sepa.confirming import CONFIRMING_MODE
from erpnext_spain.es_sepa.credit_transfer import check_role
from erpnext_spain.es_sepa.direct_debit import DIRECT_DEBIT_MODE
from erpnext_spain.utils.gating import is_pgc_company

PAYMENT_ENTRY = "Payment Entry"
# Formas de pago con su propia remesa: sus vencimientos no van en órdenes de pago.
OTHER_REMITTANCE_MODES = (CONFIRMING_MODE, DIRECT_DEBIT_MODE)


def is_transfer_mode(mode: str | None) -> bool:
	"""Vencimiento que se paga por transferencia: sin forma de pago o con una de tipo banco."""
	if not mode:
		return True
	if mode in OTHER_REMITTANCE_MODES:
		return False
	return frappe.get_cached_value("Mode of Payment", mode, "type") == "Bank"


def supplier_account(supplier: str) -> str | None:
	return frappe.db.get_value(
		"Bank Account", {"party_type": "Supplier", "party": supplier, "is_default": 1, "disabled": 0}, "name"
	) or frappe.db.get_value(
		"Bank Account", {"party_type": "Supplier", "party": supplier, "disabled": 0}, "name"
	)


@frappe.whitelist()
def get_effects(
	company: str,
	suppliers: list | str | None = None,
	payment_terms_templates: list | str | None = None,
	from_due_date: str | None = None,
	to_due_date: str | None = None,
	min_amount: float | None = None,
	max_amount: float | None = None,
	batch: str | None = None,
) -> list[dict]:
	"""Vencimientos pendientes de facturas de compra que se pagan por transferencia,
	sin los que ya están en pagos en borrador de otras órdenes."""
	frappe.has_permission("Purchase Invoice", "read", throw=True)
	frappe.has_permission("Payment Order", "read", throw=True)
	found = effects.pending_effects(
		"Purchase Invoice",
		"supplier",
		company,
		["supplier_name", "bill_no", "credit_to"],
		parties=effects.as_list(suppliers),
		payment_terms_templates=effects.as_list(payment_terms_templates),
	)
	found = [e for e in found if is_transfer_mode(e["mode_of_payment"])]
	found = effects.in_range(
		effects.subtract_reserved(found, reserved_effects()),
		from_due_date,
		to_due_date,
		min_amount,
		max_amount,
	)
	accounts: dict[str, str | None] = {}
	rows = []
	for effect in found:
		supplier = effect["supplier"]
		if supplier not in accounts:
			accounts[supplier] = supplier_account(supplier)
		rows.append(
			{
				"purchase_invoice": effect["invoice"],
				"supplier": supplier,
				"supplier_name": effect["supplier_name"],
				"bill_no": effect["bill_no"] or effect["invoice"],
				"payment_term": effect["payment_term"],
				"due_date": effect["due_date"],
				"amount": effect["amount"],
				"bank_account": accounts[supplier],
				"iban": frappe.get_cached_value("Bank Account", accounts[supplier], "iban")
				if accounts[supplier]
				else None,
			}
		)
	return rows


def reserved_effects() -> dict[tuple, float]:
	"""Importe de cada efecto (factura, vencimiento) en pagos en borrador creados
	desde una orden de pago. Los pagos validados ya rebajan el pendiente."""
	payment = frappe.qb.DocType(PAYMENT_ENTRY)
	reference = frappe.qb.DocType("Payment Entry Reference")
	rows = (
		frappe.qb.from_(reference)
		.join(payment)
		.on(reference.parent == payment.name)
		.select(reference.reference_name, reference.payment_term, reference.allocated_amount)
		.where(
			(reference.parenttype == PAYMENT_ENTRY)
			& (reference.reference_doctype == "Purchase Invoice")
			& (payment.docstatus == 0)
			& payment.payment_order.isnotnull()
			& (payment.payment_order != "")
		)
		.run()
	)
	reserved: dict[tuple, float] = {}
	for invoice, term, amount in rows:
		key = (invoice, term or "")
		reserved[key] = reserved.get(key, 0) + flt(amount)
	return reserved


@frappe.whitelist(methods=["POST"])
def add_effects(
	effects_to_add: list | str,
	payment_order: str | None = None,
	company: str | None = None,
	company_bank_account: str | None = None,
	posting_date: str | None = None,
	execution_date: str | None = None,
) -> str:
	"""Crea los pagos en borrador de los efectos y los añade a la orden. Sin
	`payment_order`, crea la orden con los datos indicados. Devuelve la orden."""
	check_role()
	if payment_order:
		order = frappe.get_doc("Payment Order", payment_order)
		order.check_permission("write")
		if order.docstatus != 0:
			frappe.throw(_("Solo se pueden añadir efectos a una orden de pago en borrador."))
	else:
		frappe.has_permission("Payment Order", "create", throw=True)
		order = frappe.get_doc(
			{
				"doctype": "Payment Order",
				"company": company,
				"company_bank_account": company_bank_account,
				"posting_date": posting_date or nowdate(),
				"es_sepa_execution_date": execution_date,
				"payment_order_type": PAYMENT_ENTRY,
			}
		)
	if order.payment_order_type and order.payment_order_type != PAYMENT_ENTRY:
		frappe.throw(
			_("La orden de pago es de solicitudes de pago: los efectos solo se añaden a órdenes de pagos.")
		)
	if not is_pgc_company(order.company):
		frappe.throw(_("La compañía {0} no tiene el plan PGC aplicado.").format(frappe.bold(order.company)))
	ledger = frappe.db.get_value(
		"Bank Account", order.company_bank_account, ["account", "company", "is_company_account"], as_dict=True
	)
	if not ledger or not ledger.is_company_account or ledger.company != order.company:
		frappe.throw(_("Indique una cuenta bancaria de la compañía en la orden de pago."))

	requested = frappe.parse_json(effects_to_add) if isinstance(effects_to_add, str) else effects_to_add
	if not requested:
		frappe.throw(_("Marque al menos un efecto."))
	groups = check_requested(order.company, requested)

	order.payment_order_type = PAYMENT_ENTRY
	payments = []
	for (supplier, payable), rows in groups.items():
		payment = draft_payment(order, supplier, payable, ledger.account, rows)
		payments.append(payment)
		order.append(
			"references",
			{
				"reference_doctype": PAYMENT_ENTRY,
				"reference_name": payment.name,
				"amount": payment.paid_amount,
				"supplier": supplier,
				"bank_account": payment.party_bank_account,
				"account": payable,
				"mode_of_payment": payment.mode_of_payment,
			},
		)
	if payment_order:
		order.save()
	else:
		order.insert()
	for payment in payments:
		payment.db_set("payment_order", order.name)
	return order.name


def check_requested(company: str, requested: list[dict]) -> dict[tuple, list[dict]]:
	"""Comprueba los efectos contra los disponibles (no se fía del navegador) y los
	agrupa por proveedor y cuenta a pagar."""
	suppliers = sorted({row.get("supplier") for row in requested if row.get("supplier")})
	available = {
		(e["purchase_invoice"], e["payment_term"] or ""): e for e in get_effects(company, suppliers=suppliers)
	}
	groups: dict[tuple, list[dict]] = {}
	missing_accounts = set()
	for row in requested:
		key = (row.get("purchase_invoice"), row.get("payment_term") or "")
		effect = available.get(key)
		if (
			not effect
			or flt(row.get("amount")) <= 0
			or flt(row.get("amount")) > flt(effect["amount"]) + 0.005
		):
			frappe.throw(
				_(
					"El efecto de la factura {0} ya no está pendiente por ese importe. Busque de nuevo."
				).format(frappe.bold(key[0]))
			)
		if not effect["bank_account"]:
			missing_accounts.add(effect["supplier"])
		payable = frappe.db.get_value("Purchase Invoice", key[0], "credit_to")
		groups.setdefault((effect["supplier"], payable), []).append({**effect, "amount": flt(row["amount"])})
	if missing_accounts:
		frappe.throw(
			_("Sin cuenta bancaria (IBAN) para la transferencia: {0}. Créela en el proveedor.").format(
				", ".join(sorted(missing_accounts))
			),
			title=_("Falta la cuenta del beneficiario"),
		)
	return groups


def draft_payment(order, supplier: str, payable: str, ledger: str, rows: list[dict]):
	date = order.get("es_sepa_execution_date") or order.posting_date or nowdate()
	total = sum(flt(row["amount"]) for row in rows)
	payment = frappe.new_doc(PAYMENT_ENTRY)
	payment.update(
		{
			"payment_type": "Pay",
			"company": order.company,
			"posting_date": date,
			"party_type": "Supplier",
			"party": supplier,
			"paid_from": ledger,
			"paid_to": payable,
			"paid_amount": total,
			"received_amount": total,
			"bank_account": order.company_bank_account,
			"party_bank_account": rows[0]["bank_account"],
			"payment_order_status": "Initiated",
			**(
				{"mode_of_payment": "Wire Transfer"}
				if frappe.db.exists("Mode of Payment", "Wire Transfer")
				else {}
			),
		}
	)
	for row in rows:
		payment.append(
			"references",
			{
				"reference_doctype": "Purchase Invoice",
				"reference_name": row["purchase_invoice"],
				"allocated_amount": flt(row["amount"]),
				**({"payment_term": row["payment_term"]} if row["payment_term"] else {}),
			},
		)
	payment.setup_party_account_field()
	payment.set_missing_values()
	# set_missing_values vacía la referencia bancaria: se fija después.
	payment.reference_no = order.name or _("Orden de pago")
	payment.reference_date = date
	payment.insert()
	return payment


# --- ciclo de la orden (doc_events de Payment Order) --------------------------------


def own_drafts(order_name: str) -> list[str]:
	return frappe.get_all(PAYMENT_ENTRY, filters={"payment_order": order_name, "docstatus": 0}, pluck="name")


def on_update(doc, method=None) -> None:
	"""Borra los pagos en borrador de la orden que ya no están en su tabla."""
	if doc.docstatus != 0 or not is_pgc_company(doc.company):
		return
	referenced = {r.reference_name for r in doc.references if r.reference_doctype == PAYMENT_ENTRY}
	for name in own_drafts(doc.name):
		if name not in referenced:
			# force: el pago y la orden se enlazan entre sí.
			frappe.delete_doc(PAYMENT_ENTRY, name, force=True)


def on_submit(doc, method=None) -> None:
	"""Valida los pagos en borrador creados desde la orden, con su fecha de ejecución."""
	if not is_pgc_company(doc.company):
		return
	drafts = set(own_drafts(doc.name))
	if not drafts:
		return
	date = getdate(doc.get("es_sepa_execution_date") or doc.posting_date or nowdate())
	for row in doc.references:
		if row.reference_doctype != PAYMENT_ENTRY or row.reference_name not in drafts:
			continue
		payment = frappe.get_doc(PAYMENT_ENTRY, row.reference_name)
		payment.posting_date = date
		payment.reference_date = date
		payment.reference_no = doc.name
		payment.submit()


def on_trash(doc, method=None) -> None:
	if not is_pgc_company(doc.company):
		return
	for name in own_drafts(doc.name):
		frappe.delete_doc(PAYMENT_ENTRY, name, force=True)
