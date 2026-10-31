# Inmueble arrendado (spec 08 §3): datos del inmueble para el modelo 180.

import re

import frappe
from frappe import _
from frappe.model.document import Document

CADASTRAL_REFERENCE = re.compile(r"^[0-9A-Z]{20}$")


class ESLeasedProperty(Document):
	def validate(self):
		if self.cadastral_reference:
			self.cadastral_reference = self.cadastral_reference.replace(" ", "").upper()
			if not CADASTRAL_REFERENCE.match(self.cadastral_reference):
				frappe.throw(
					_(
						"La referencia catastral {0} no es válida: debe tener 20 letras o números"
						" (sin espacios). Cópiela del recibo del IBI o de la Sede Electrónica del Catastro."
					).format(frappe.bold(self.cadastral_reference)),
					title=_("Referencia catastral"),
				)
