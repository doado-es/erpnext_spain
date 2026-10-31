# Declaración de un modelo de la AEAT (spec 07): cálculo revisable y fichero.
# La lógica de cada modelo está en es_modelos/model_303.py y model_111.py.

import frappe
from frappe.model.document import Document


class ESTaxReturn(Document):
	def validate(self):
		from erpnext_spain.es_modelos import returns

		if not self.boxes:
			returns.calculate(self)
		returns.compute_totals(self)

	def on_submit(self):
		from erpnext_spain.es_modelos import returns

		returns.attach_file(self)
