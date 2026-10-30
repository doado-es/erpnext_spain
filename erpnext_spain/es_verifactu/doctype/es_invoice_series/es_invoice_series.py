# Child table «ES Invoice Series» (spec 04 §2.1): filas {serie, tipo AEAT} de
# UNA compañía — el mapeo serie↔tipo vive POR EMPRESA (defecto corregido de la
# referencia, que llevaba las series globales en el catálogo). La biyección y
# la no-compartición entre empresas se validan en el doc_event de Company
# (erpnext_spain/verifactu/company.py).

from __future__ import annotations

from frappe.model.document import Document


class ESInvoiceSeries(Document):
	pass
