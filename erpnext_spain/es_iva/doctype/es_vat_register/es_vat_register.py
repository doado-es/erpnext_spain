# Registro Fiscal IVA (spec 06 §1): una fila por parte del desglose fiscal de
# cada factura. Lo escribe el sistema (es_iva/register.py); no se edita.

import frappe
from frappe.model.document import Document


class ESVatRegister(Document):
	pass


def on_doctype_update():
	frappe.db.add_index("ES Vat Register", ["company", "book", "posting_date"])
	frappe.db.add_index("ES Vat Register", ["voucher_type", "voucher_no"])
