# Factura electrónica emitida (spec 10 §2). La escribe solo el sistema
# (es_efactura/api.py): todos los campos son de solo lectura y los permisos de
# los usuarios son de lectura. El XML firmado no se modifica una vez generado.

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class ESEInvoice(Document):
	def add_history(self, status: str, note: str | None = None) -> None:
		self.append(
			"history",
			{
				"date": frappe.utils.now_datetime(),
				"status": status,
				"note": note,
				"user": frappe.session.user,
			},
		)

	def on_trash(self):
		if self.status not in ("Generada", "Anulada"):
			frappe.throw(
				_("No se puede borrar la factura electrónica {0}: ya se presentó en FACe ({1}).").format(
					self.name, self.status
				)
			)
