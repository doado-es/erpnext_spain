# Remesa de adeudos SEPA (spec 11 §5). La lógica está en es_sepa/direct_debit.py.

from frappe.model.document import Document


class ESSepaDirectDebitBatch(Document):
	def validate(self):
		from erpnext_spain.es_sepa.direct_debit import validate_batch

		validate_batch(self)

	def on_submit(self):
		from erpnext_spain.es_sepa.direct_debit import submit_batch

		submit_batch(self)

	def on_cancel(self):
		from erpnext_spain.es_sepa.direct_debit import cancel_batch

		cancel_batch(self)
