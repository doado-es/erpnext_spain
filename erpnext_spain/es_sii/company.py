# Validación de Company del SII (spec 14 §1).

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


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
