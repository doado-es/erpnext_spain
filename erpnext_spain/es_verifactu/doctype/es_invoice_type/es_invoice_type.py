# Catálogo «ES Invoice Type» (spec 04 §2.1): SOLO códigos y
# semántica de los tipos de factura — SIN series globales (defecto corregido
# de la referencia: las series viven por empresa en el mapeo «ES Verifactu
# Series» del tab Spain Compliance de la Company).
#
# La siembra del catálogo completo (F1–F3, R1–R5) es código idempotente en
# erpnext_spain/es_verifactu/catalog.py, invocado desde after_install y
# after_migrate (doc 12 §11: código, no fixtures JSON).

from __future__ import annotations

from frappe.model.document import Document

import frappe


class ESInvoiceType(Document):
	def before_insert(self):
		# La normalización del código DEBE correr antes del naming: con
		# autoname «field:code» el docname se fija en set_new_name, que va
		# ANTES de validate en el flujo de insert, y luego
		# _sync_autoname_field reescribe el campo con el name ya fijado —
		# normalizar solo en validate llega tarde (el name quedaría «t9»).
		self.code = (self.code or "").strip().upper()

	def validate(self):
		self.code = (self.code or "").strip().upper()
		self.label = (self.label or "").strip()
		if self.rectification_type:
			self.rectification_type = self.rectification_type.strip().upper()
