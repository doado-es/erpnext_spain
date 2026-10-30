# Validación de Company del SII (spec 14 §1).

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

SII_PURPOSE = "SII"


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
	credential = doc.get("es_sii_credential")
	if credential:
		values = frappe.db.get_value("ES AEAT Credential", credential, ["company", "purpose"], as_dict=True)
		if not values or values.company != doc.name or values.purpose != SII_PURPOSE:
			frappe.throw(
				_("La credencial {0} debe ser de la compañía {1} y tener el propósito SII.").format(
					frappe.bold(credential), frappe.bold(doc.name)
				),
				title=_("SII"),
			)
