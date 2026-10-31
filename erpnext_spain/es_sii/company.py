# Validación de Company del SII (spec 14 §1).

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, format_date, getdate

from erpnext_spain.es_sii.outbox import WORKING_DAYS, recompute_send_on


def validate(doc: Document, method: str | None = None) -> None:
	if cint(doc.get("es_sii_enabled")) and cint(doc.get("es_verifactu_enabled")):
		frappe.throw(
			_(
				"{0} no puede tener activados a la vez el SII y VeriFactu: quien lleva los libros"
				" registro por el SII queda fuera de VeriFactu. Desactive uno de los dos."
			).format(frappe.bold(doc.name)),
			title=_("SII y VeriFactu"),
		)
	if not cint(doc.get("es_sii_enabled")):
		return
	if not doc.get("tax_id"):
		frappe.throw(
			_("Para activar el SII, informe el NIF de la compañía {0} (campo Tax ID).").format(
				frappe.bold(doc.name)
			),
			title=_("SII"),
		)
	start, end = doc.get("es_sii_activation_date"), doc.get("es_sii_end_date")
	if start and end and getdate(end) < getdate(start):
		frappe.throw(
			_("La fecha de fin en el SII ({0}) es anterior a la de inicio ({1}).").format(
				format_date(end), format_date(start)
			),
			title=_("SII"),
		)
	days = cint(doc.get("es_sii_wait_days"))
	if days > WORKING_DAYS:
		frappe.msgprint(
			_(
				"Con {0} días hábiles de espera, las facturas se enviarán al vencer el plazo legal"
				" ({1} días hábiles; las recibidas, como tarde el día 15 del mes siguiente)."
			).format(days, WORKING_DAYS),
			title=_("SII"),
			indicator="orange",
		)
	if not doc.is_new() and doc.has_value_changed("es_sii_wait_days"):
		# Las altas pendientes se recalculan con los días nuevos.
		recompute_send_on(doc.name, days)
