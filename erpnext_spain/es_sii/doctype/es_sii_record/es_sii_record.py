# Registro del SII (spec 14 §3). Inalterable: lo escribe es_sii/outbox.py.

import frappe
from frappe.model.document import Document


class ESSiiRecord(Document):
	pass


def on_doctype_update():
	frappe.db.add_index("ES Sii Record", ["company", "status", "book"])
