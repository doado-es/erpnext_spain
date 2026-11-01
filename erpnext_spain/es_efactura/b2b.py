# Factura electrónica B2B (spec 10 §5): emisión, canal, recepción y estados.
#
# Canal (decisión A9 pendiente): adaptador con interfaz común. Hoy existen
# «Descarga manual» (el fichero queda adjunto para subirlo a mano) y «Simulado»
# (pruebas). La SPFE de la AEAT y la plataforma privada llegarán como
# adaptadores cuando haya documentación técnica y proveedor.

import hashlib

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

from erpnext_spain.es_efactura import ubl
from erpnext_spain.utils.gating import is_feature_enabled

DOCTYPE = "ES E-Invoice"
B2B_FLAG = "es_einvoice_b2b"
ROLES = ("Accounts Manager", "System Manager")
DEADLINE_DAYS = 4


class ChannelAdapter:
	"""Interfaz común de los canales B2B."""

	def send(self, e_invoice, content: bytes) -> str | None:
		"""Envía la factura; devuelve el identificador del canal."""
		raise NotImplementedError

	def receive(self, company: str) -> list[bytes]:
		raise NotImplementedError

	def communicate_state(self, e_invoice, state: str, date, reason: str | None = None) -> None:
		raise NotImplementedError


class ManualAdapter(ChannelAdapter):
	"""Sin envío: el usuario descarga el fichero y lo sube a su plataforma."""

	def send(self, e_invoice, content):
		return None

	def receive(self, company):
		return []

	def communicate_state(self, e_invoice, state, date, reason=None):
		e_invoice.add_history(_("{0} (comunicar a mano)").format(state), reason or "")


class SimulatedAdapter(ChannelAdapter):
	"""Canal de pruebas: guarda lo enviado en `frappe.flags.es_einvoice_outbox`."""

	def send(self, e_invoice, content):
		frappe.flags.es_einvoice_outbox = [*(frappe.flags.es_einvoice_outbox or []), content]
		return f"SIM-{e_invoice.name}"

	def receive(self, company):
		return list((frappe.flags.es_einvoice_inbox or {}).get(company, []))

	def communicate_state(self, e_invoice, state, date, reason=None):
		frappe.flags.es_einvoice_states = [
			*(frappe.flags.es_einvoice_states or []),
			(e_invoice.name, state, str(date), reason),
		]


ADAPTERS = {"Descarga manual": ManualAdapter, "Simulado": SimulatedAdapter}


def adapter_for(company: str) -> ChannelAdapter:
	channel = frappe.get_cached_value("Company", company, "es_einvoice_channel") or "Descarga manual"
	adapter = ADAPTERS.get(channel)
	if not adapter:
		frappe.throw(_("El canal {0} aún no está disponible. Use «Descarga manual».").format(channel))
	return adapter()


def check_role() -> None:
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("No tiene permiso para gestionar facturas electrónicas."), frappe.PermissionError)


def attach(doc, file_name: str, content: bytes) -> str:
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": 1,
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": doc.name,
			"attached_to_field": "file",
		}
	).insert(ignore_permissions=True)
	return file.file_url


# --- emisión ------------------------------------------------------------------------------


def is_b2b_customer(customer: str) -> bool:
	"""Empresario o profesional en España: con NIF español y no Administración Pública."""
	from erpnext_spain.es_nif import validator

	values = frappe.get_cached_value(
		"Customer", customer, ["tax_id", "es_public_administration"], as_dict=True
	)
	return bool(
		values
		and values.tax_id
		and not values.es_public_administration
		and validator.looks_spanish(values.tax_id)
	)


def on_submit(doc, method=None) -> None:
	"""Sales Invoice: genera y envía la factura UBL a los clientes B2B."""
	if not is_feature_enabled(doc.company, B2B_FLAG) or not is_b2b_customer(doc.customer):
		return
	issue(doc)


def issue(si) -> str:
	content = ubl.render(ubl.build(si))
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"direction": "Emitida",
			"scope": "B2B",
			"sales_invoice": si.name,
			"company": si.company,
			"customer": si.customer,
			"invoice_date": si.posting_date,
			"invoice_total": si.grand_total,
			"currency": si.currency,
			"format": "UBL 2.1",
			"channel": frappe.get_cached_value("Company", si.company, "es_einvoice_channel")
			or "Descarga manual",
			"status": "Generada",
			"file_hash": hashlib.sha256(content).hexdigest(),
		}
	)
	doc.add_history("Generada", _("UBL 2.1 (EN 16931)"))
	doc.insert(ignore_permissions=True)
	doc.db_set("file", attach(doc, f"{si.name.replace('/', '-')}.xml", content))
	frappe.enqueue(
		"erpnext_spain.es_efactura.b2b.send",
		queue="short",
		e_invoice=doc.name,
		enqueue_after_commit=True,
		now=frappe.flags.in_test,
	)
	return doc.name


def send(e_invoice: str) -> None:
	doc = frappe.get_doc(DOCTYPE, e_invoice)
	if doc.status != "Generada":
		return
	adapter = adapter_for(doc.company)
	file = frappe.get_doc("File", {"file_url": doc.file})
	content = file.get_content()
	external_id = adapter.send(doc, content if isinstance(content, bytes) else content.encode())
	if external_id:
		doc.external_id = external_id
		doc.status = "Enviada"
		doc.add_history("Enviada", external_id)
		doc.save(ignore_permissions=True)


# --- recepción -------------------------------------------------------------------------------


def find_supplier(tax_id: str) -> str | None:
	for value in (tax_id, f"ES{tax_id}"):
		supplier = frappe.db.get_value("Supplier", {"tax_id": value, "disabled": 0}, "name")
		if supplier:
			return supplier
	return None


def receive_invoice(company: str, content: bytes, source: str = "Simulado") -> str:
	"""Registra una factura recibida: borrador de Purchase Invoice si se conoce el
	proveedor; si no, queda pendiente de proveedor. Nunca se valida sola."""
	data = ubl.parse(content)
	supplier = find_supplier(data.seller_tax_id)
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"direction": "Recibida",
			"scope": "B2B",
			"company": company,
			"supplier": supplier,
			"sender_tax_id": data.seller_tax_id,
			"supplier_invoice_number": data.number,
			"invoice_date": data.issue_date,
			"invoice_total": flt(data.total),
			"currency": "EUR",
			"format": "UBL 2.1",
			"channel": source,
			"status": "Generada" if supplier else "Pendiente de proveedor",
			"file_hash": hashlib.sha256(content).hexdigest(),
			"state_deadline": state_deadline(nowdate()),
		}
	)
	doc.add_history(_("Recibida"), data.seller_name)
	doc.insert(ignore_permissions=True)
	doc.db_set("file", attach(doc, f"{data.number.replace('/', '-')}.xml", content))
	if supplier:
		doc.db_set("purchase_invoice", draft_purchase_invoice(company, supplier, data, doc.name))
	return doc.name


def state_deadline(date):
	from erpnext_spain.es_sii.outbox import add_working_days

	return add_working_days(date, DEADLINE_DAYS)


def draft_purchase_invoice(company: str, supplier: str, data, e_invoice: str) -> str:
	expense = frappe.get_cached_value("Company", company, "default_expense_account")
	cost_center = frappe.get_cached_value("Company", company, "cost_center")
	pi = frappe.new_doc("Purchase Invoice")
	pi.update(
		{
			"company": company,
			"supplier": supplier,
			"bill_no": data.number,
			"bill_date": data.issue_date,
			"posting_date": nowdate(),
			"is_return": 1 if data.credit_note else 0,
			"es_e_invoice": e_invoice,
		}
	)
	if data.due_date and not data.credit_note:
		pi.due_date = getdate(data.due_date)
	sign = -1 if data.credit_note else 1
	for line in data.lines:
		qty = line["qty"] or 1
		pi.append(
			"items",
			{
				"item_name": line["description"][:140] or _("Línea de la factura electrónica"),
				"description": line["description"],
				"qty": sign * qty,
				"rate": abs(line["amount"]) / qty,
				"uom": "Nos",
				"expense_account": expense,
				"cost_center": cost_center,
			},
		)
	pi.set_missing_values()
	if not pi.taxes_and_charges:
		pi.taxes_and_charges = frappe.db.get_value(
			"Purchase Taxes and Charges Template",
			{"company": company, "is_default": 1, "disabled": 0},
			"name",
		)
	if pi.taxes_and_charges and not pi.get("taxes"):
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		pi.set("taxes", get_taxes_and_charges("Purchase Taxes and Charges Template", pi.taxes_and_charges))
	pi.flags.ignore_mandatory = True
	pi.insert(ignore_permissions=True)
	return pi.name


@frappe.whitelist(methods=["POST"])
def fetch_received(company: str) -> list[str]:
	"""Trae las facturas recibidas del canal de la compañía."""
	check_role()
	frappe.get_doc("Company", company).check_permission("read")
	return [
		receive_invoice(company, content, frappe.get_cached_value("Company", company, "es_einvoice_channel"))
		for content in adapter_for(company).receive(company)
	]


@frappe.whitelist(methods=["POST"])
def upload_received(company: str, file_url: str) -> str:
	"""Registra a mano un UBL recibido por otra vía."""
	check_role()
	file = frappe.get_doc("File", {"file_url": file_url})
	file.check_permission("read")
	content = file.get_content()
	return receive_invoice(
		company, content if isinstance(content, bytes) else content.encode(), "Descarga manual"
	)


# --- estados que comunica la compañía como receptora -------------------------------------------


@frappe.whitelist(methods=["POST"])
def accept_or_reject(e_invoice: str, accept: bool = True, reason: str | None = None) -> str:
	check_role()
	doc = frappe.get_doc(DOCTYPE, e_invoice)
	doc.check_permission("write")
	if doc.direction != "Recibida":
		frappe.throw(_("Solo se aceptan o rechazan facturas recibidas."))
	if not accept and not (reason or "").strip():
		frappe.throw(_("Indique el motivo del rechazo."))
	state = "Aceptada" if accept else "Rechazada"
	adapter_for(doc.company).communicate_state(doc, state, nowdate(), reason)
	doc.status = state
	doc.add_history(state, reason or "")
	doc.save(ignore_permissions=True)
	return state


def payment_changed(doc, method=None) -> None:
	"""Payment Entry / Journal Entry on_submit y on_cancel: marca la comunicación
	del pago efectivo completo de las facturas recibidas, o la retira."""
	if doc.doctype == "Payment Entry":
		invoices = [r.reference_name for r in doc.references if r.reference_doctype == "Purchase Invoice"]
		date = doc.posting_date
	else:
		invoices = [r.reference_name for r in doc.accounts if r.reference_type == "Purchase Invoice"]
		date = doc.posting_date
	for invoice in set(invoices):
		name = frappe.db.get_value(DOCTYPE, {"purchase_invoice": invoice, "direction": "Recibida"}, "name")
		if not name:
			continue
		outstanding = flt(frappe.db.get_value("Purchase Invoice", invoice, "outstanding_amount"))
		e_invoice = frappe.get_doc(DOCTYPE, name)
		if (
			doc.docstatus == 1
			and abs(outstanding) < 0.005
			and e_invoice.payment_communication != "Comunicada"
		):
			e_invoice.db_set(
				{
					"payment_communication": "Pendiente",
					"payment_date": date,
					"state_deadline": state_deadline(date),
				}
			)
		elif doc.docstatus == 2 and e_invoice.payment_communication == "Pendiente":
			e_invoice.db_set({"payment_communication": "", "payment_date": None})


def communicate_payments() -> None:
	"""Job: comunica los pagos efectivos pendientes y avisa de los plazos."""
	for name in frappe.get_all(DOCTYPE, filters={"payment_communication": "Pendiente"}, pluck="name"):
		doc = frappe.get_doc(DOCTYPE, name)
		try:
			adapter_for(doc.company).communicate_state(doc, "Pagada", doc.payment_date)
		except Exception:
			frappe.log_error(title=_("Comunicación de pago de {0}").format(name))
			continue
		doc.payment_communication = "Comunicada"
		doc.status = "Pagada"
		doc.add_history("Pagada", str(doc.payment_date))
		doc.save(ignore_permissions=True)
	overdue = frappe.get_all(
		DOCTYPE,
		filters={
			"direction": "Recibida",
			"status": ["in", ["Generada", "Pendiente de proveedor"]],
			"state_deadline": ["<=", add_days(nowdate(), 1)],
		},
		fields=["name", "company"],
	)
	for row in overdue:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": "Administrator",
				"type": "Alert",
				"document_type": DOCTYPE,
				"document_name": row.name,
				"subject": _("La factura recibida {0} debe aceptarse o rechazarse antes de mañana.").format(
					row.name
				),
			}
		).insert(ignore_permissions=True)
