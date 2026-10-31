# Configuración de un agregador bancario (spec 13 §3). Las credenciales van en
# campos Password: Frappe no las devuelve en la API.

from frappe.model.document import Document


class ESBankAggregator(Document):
	pass
