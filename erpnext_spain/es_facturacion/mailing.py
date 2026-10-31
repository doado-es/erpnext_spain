# Envío masivo de facturas por correo (spec 15, F3).
#
# En segundo plano; una factura por correo o todas las de un cliente en uno, con
# el formato de impresión español y la plantilla de correo «ES Factura». Lo ya
# enviado no se reenvía salvo que se pida; cada envío queda en ES Invoice Email Log.

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

TEMPLATE = "ES Factura"
TEMPLATE_SUBJECT = "Factura {{ doc.name }} de {{ doc.company }}"
TEMPLATE_RESPONSE = """<p>Estimado cliente:</p>
<p>Le enviamos adjunta la factura {{ doc.name }}, de fecha {{ frappe.utils.formatdate(doc.posting_date) }}, por importe de {{ doc.get_formatted("grand_total") }}.</p>
<p>Un saludo,<br>{{ doc.company }}</p>"""
ROLES = ("Accounts User", "Accounts Manager", "System Manager")
LOG = "ES Invoice Email Log"


def ensure_template() -> list[str]:
	"""Plantilla de correo de partida (spec 09, S2: no se pisa si existe)."""
	if frappe.db.exists("Email Template", TEMPLATE):
		return []
	frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": TEMPLATE,
			"subject": TEMPLATE_SUBJECT,
			"response": TEMPLATE_RESPONSE,
			"use_html": 1,
			"response_html": TEMPLATE_RESPONSE,
		}
	).insert(ignore_permissions=True)
	return [TEMPLATE]


@frappe.whitelist(methods=["POST"])
def send_invoices(sales_invoices: list | str, group_by_customer: bool = False, resend: bool = False) -> dict:
	"""Encola el envío de las facturas seleccionadas."""
	from erpnext_spain.es_facturacion.bulk import as_list

	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("No tiene permiso para enviar facturas por correo."), frappe.PermissionError)
	frappe.has_permission("Sales Invoice", "email", throw=True)
	names = as_list(sales_invoices)
	frappe.enqueue(
		"erpnext_spain.es_facturacion.mailing.run",
		queue="long",
		timeout=3600,
		names=names,
		group_by_customer=cint(group_by_customer),
		resend=cint(resend),
		user=frappe.session.user,
		now=frappe.flags.in_test,
	)
	return {"queued": True, "count": len(names)}


def recipient(invoice) -> str | None:
	if invoice.get("contact_email"):
		return invoice.contact_email
	contact = frappe.get_cached_value("Customer", invoice.customer, "customer_primary_contact")
	if contact:
		return frappe.get_cached_value("Contact", contact, "email_id")
	return frappe.get_cached_value("Customer", invoice.customer, "email_id")


def log(invoice, to: str | None, status: str, error: str | None = None) -> None:
	frappe.get_doc(
		{
			"doctype": LOG,
			"sales_invoice": invoice.name,
			"customer": invoice.customer,
			"company": invoice.company,
			"recipient": to,
			"status": status,
			"error": error,
			"sent_on": now_datetime() if status == "Enviado" else None,
		}
	).insert(ignore_permissions=True)


def run(names: list[str], group_by_customer: int = 0, resend: int = 0, user: str | None = None) -> dict:
	from erpnext_spain.es_verifactu.printing import FORMAT_NAME

	ensure_template()
	counts = {"sent": 0, "skipped": 0, "errors": 0}
	batches: dict[str, list] = {}
	for name in names:
		invoice = frappe.get_doc("Sales Invoice", name)
		if invoice.docstatus != 1:
			log(invoice, None, "Error", _("La factura no está validada."))
			counts["errors"] += 1
			continue
		if invoice.get("es_emailed_on") and not resend:
			counts["skipped"] += 1
			continue
		key = invoice.customer if group_by_customer else invoice.name
		batches.setdefault(key, []).append(invoice)

	template = frappe.get_doc("Email Template", TEMPLATE)
	for invoices in batches.values():
		first = invoices[0]
		to = recipient(first)
		if not to:
			for invoice in invoices:
				log(
					invoice,
					None,
					"Error",
					_(
						"El cliente no tiene correo de facturación (contacto principal o correo de la factura)."
					),
				)
			counts["errors"] += len(invoices)
			continue
		try:
			context = {"doc": first}
			subject = frappe.render_template(template.subject, context)
			if len(invoices) > 1:
				subject = _("Facturas de {0}").format(first.company)
			frappe.sendmail(
				recipients=[to],
				subject=subject,
				message=frappe.render_template(template.response_html or template.response, context),
				# El PDF lo genera la cola de correo al enviar, con el formato español.
				attachments=[
					{
						"print_format_attachment": 1,
						"doctype": "Sales Invoice",
						"name": invoice.name,
						"print_format": FORMAT_NAME,
					}
					for invoice in invoices
				],
				reference_doctype="Sales Invoice",
				reference_name=first.name,
				now=False,
			)
		except Exception as error:
			for invoice in invoices:
				log(invoice, to, "Error", str(error)[:500])
			counts["errors"] += len(invoices)
			continue
		for invoice in invoices:
			invoice.db_set("es_emailed_on", now_datetime(), update_modified=False)
			log(invoice, to, "Enviado")
		counts["sent"] += len(invoices)
	if user:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"subject": _("Envío de facturas: {0} enviadas, {1} ya enviadas antes, {2} con error.").format(
					counts["sent"], counts["skipped"], counts["errors"]
				),
			}
		).insert(ignore_permissions=True)
	return counts
