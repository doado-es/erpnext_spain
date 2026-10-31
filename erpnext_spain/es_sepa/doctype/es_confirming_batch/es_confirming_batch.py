# Remesa de confirming (spec 12 §2-§4). La lógica está en es_sepa/confirming.py.

from frappe.model.document import Document


class ESConfirmingBatch(Document):
	def validate(self):
		from erpnext_spain.es_sepa.confirming import validate_batch

		validate_batch(self)

	def on_submit(self):
		from erpnext_spain.es_sepa.confirming import submit_batch

		submit_batch(self)
