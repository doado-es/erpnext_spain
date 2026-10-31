# Acciones de la factura electrónica (spec 10 §2 y §4): generar el Facturae
# firmado de una factura de venta y registrar a mano su presentación en FACe.

import hashlib

import frappe
from frappe import _

from erpnext_spain.es_efactura import facturae, signer

DOCTYPE = "ES E-Invoice"
ROLES = ("Accounts Manager", "Accounts User", "System Manager")
OPEN_STATUSES = ("Registrada en FACe", "Contabilizada", "Pagada")
MANUAL_STATUSES = ("Contabilizada", "Pagada", "Rechazada", "Anulada")


def check_role() -> None:
	if not set(ROLES) & set(frappe.get_roles()):
		frappe.throw(_("No tiene permiso para gestionar facturas electrónicas."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def generate_facturae(sales_invoice: str) -> str:
	"""Genera, firma y valida el Facturae de una factura de venta validada y crea
	su ES E-Invoice. Devuelve el nombre del registro."""
	check_role()
	si = frappe.get_doc("Sales Invoice", sales_invoice)
	si.check_permission("write")
	if frappe.get_cached_value("Company", si.company, "country") != "Spain":
		frappe.throw(_("La factura electrónica Facturae solo se genera para compañías de España."))
	if not frappe.get_cached_value("Customer", si.customer, "es_public_administration"):
		frappe.throw(
			_(
				"El cliente {0} no está marcado como Administración Pública. La primera versión genera Facturae para"
				" presentar en FACe; márquelo en su ficha (sección Factura electrónica) y complete sus códigos DIR3."
			).format(frappe.bold(si.customer))
		)

	previous = frappe.get_all(
		DOCTYPE,
		filters={"sales_invoice": si.name, "status": ["not in", ["Rechazada", "Anulada"]]},
		fields=["name", "status"],
	)
	for row in previous:
		if row.status in OPEN_STATUSES:
			frappe.throw(
				_(
					"La factura {0} ya está presentada en FACe ({1}, {2}). Para corregirla, emita una factura"
					" rectificativa."
				).format(si.name, row.name, row.status)
			)

	model = facturae.build_model(si)
	root = facturae.render(model)
	signed, subject = signer.sign(root, si.company)

	from lxml import etree

	xml = etree.tostring(signed, xml_declaration=True, encoding="UTF-8")
	facturae.validate_xml(xml)

	for row in previous:  # versiones aún no presentadas: quedan sustituidas
		old = frappe.get_doc(DOCTYPE, row.name)
		old.status = "Anulada"
		old.add_history("Anulada", _("Sustituida por una nueva generación"))
		old.save(ignore_permissions=True)

	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"sales_invoice": si.name,
			"company": si.company,
			"customer": si.customer,
			"invoice_date": si.posting_date,
			"invoice_total": si.grand_total,
			"currency": si.currency,
			"status": "Generada",
			"file_hash": hashlib.sha256(xml).hexdigest(),
			"signing_certificate": subject[:140],
		}
	)
	doc.add_history("Generada", _("Facturae 3.2.2 firmado"))
	doc.insert(ignore_permissions=True)

	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{safe(si.name)}.xsig",
			"content": xml,
			"is_private": 1,
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": doc.name,
			"attached_to_field": "file",
		}
	).insert(ignore_permissions=True)
	doc.db_set("file", file.file_url)
	update_invoice(si.name, doc.name, "Generada")
	return doc.name


@frappe.whitelist(methods=["POST"])
def register_in_face(e_invoice: str, registry_number: str, registry_date: str | None = None) -> None:
	"""Anota el número de registro que devuelve FACe al subir la factura."""
	check_role()
	doc = frappe.get_doc(DOCTYPE, e_invoice)
	frappe.get_doc("Sales Invoice", doc.sales_invoice).check_permission("write")
	if doc.face_registry_number:
		frappe.throw(_("La factura electrónica {0} ya tiene número de registro de FACe.").format(doc.name))
	if doc.status != "Generada":
		frappe.throw(
			_("Solo se registran en FACe facturas electrónicas en estado Generada ({0} está {1}).").format(
				doc.name, doc.status
			)
		)
	registry_number = (registry_number or "").strip()
	if not registry_number:
		frappe.throw(_("Indique el número de registro que le ha dado FACe."))
	doc.face_registry_number = registry_number
	doc.face_registry_date = registry_date or frappe.utils.now_datetime()
	doc.status = "Registrada en FACe"
	doc.add_history(doc.status, _("Número de registro {0}").format(registry_number))
	doc.save(ignore_permissions=True)
	update_invoice(doc.sales_invoice, doc.name, doc.status)


@frappe.whitelist(methods=["POST"])
def set_status(e_invoice: str, status: str, note: str | None = None) -> None:
	"""Cambia el estado según lo que indique FACe (contabilizada, pagada, rechazada…)."""
	check_role()
	if status not in MANUAL_STATUSES:
		frappe.throw(_("Estado no válido: {0}.").format(status))
	doc = frappe.get_doc(DOCTYPE, e_invoice)
	frappe.get_doc("Sales Invoice", doc.sales_invoice).check_permission("write")
	if status in ("Contabilizada", "Pagada") and not doc.face_registry_number:
		frappe.throw(_("Registre primero el número de registro de FACe."))
	doc.status = status
	doc.add_history(status, note)
	doc.save(ignore_permissions=True)
	update_invoice(doc.sales_invoice, doc.name, status)


def update_invoice(sales_invoice: str, e_invoice: str, status: str) -> None:
	frappe.db.set_value(
		"Sales Invoice",
		sales_invoice,
		{"es_einvoice": e_invoice, "es_einvoice_status": status},
		update_modified=False,
	)


def safe(name: str) -> str:
	return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def block_cancel_if_presented(doc, method: str | None = None) -> None:
	"""doc_event before_cancel de Sales Invoice: una factura presentada en FACe no
	se cancela; se corrige con una rectificativa."""
	if doc.get("es_einvoice_status") in OPEN_STATUSES:
		frappe.throw(
			_(
				"La factura {0} está presentada en FACe ({1}). No se puede cancelar: emita una factura rectificativa."
			).format(doc.name, doc.es_einvoice_status)
		)
