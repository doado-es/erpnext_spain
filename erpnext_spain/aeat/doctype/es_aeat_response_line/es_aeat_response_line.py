# Copyright (c) 2026, ct.galega and contributors
# For license information, please see license.txt

# Línea de respuesta AEAT (child de ES AEAT Response, spec 13 §3): el `parent`
# automático de la child table ES el link a la respuesta.

from frappe.model.document import Document


class ESAEATResponseLine(Document):
	pass