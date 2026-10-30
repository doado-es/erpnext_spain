# Copyright (c) 2026, ct.galega and contributors
# For license information, please see license.txt

# Línea de resultado de la consulta AEAT (child de ES Verifactu Aeat Query,
# spec 04 §10): una fila por registro que la AEAT devolvió — el `parent`
# automático de la child table ES el link a la consulta.

from frappe.model.document import Document


class ESVerifactuAeatQueryLine(Document):
	pass
