# Copyright (c) 2026, ct.galega and contributors
# For license information, please see license.txt

# Respuesta AEAT normalizada por servicio (spec 13 §3): crudo + parseado por
# líneas. La crea el AEATOutboxManager tras cada envío; los procesadores de
# cada funcionalidad (VeriFactu/SII) consumen las líneas por `external_ref`.
# `in_create`: solo el manager crea — los usuarios solo consultan.

from frappe.model.document import Document


class ESAEATResponse(Document):
	pass