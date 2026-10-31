# Mandato SEPA (spec 11 §3).

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, getdate, nowdate

REFERENCE = re.compile(r"^[A-Za-z0-9+?/\-:().,' ]{1,35}$")
EXPIRY_MONTHS = 36


class ESSepaMandate(Document):
	def validate(self):
		if not REFERENCE.match(self.mandate_reference or ""):
			frappe.throw(
				_(
					"La referencia del mandato {0} no es válida: hasta 35 caracteres entre letras, números"
					" y + ? / - : ( ) . , '"
				).format(frappe.bold(self.mandate_reference))
			)
		party = frappe.db.get_value("Bank Account", self.bank_account, ["party_type", "party"], as_dict=True)
		if party and (party.party_type != "Customer" or party.party != self.customer):
			frappe.throw(
				_("La cuenta bancaria {0} no es del cliente {1}. Elija una cuenta del deudor.").format(
					frappe.bold(self.bank_account), frappe.bold(self.customer)
				)
			)
		if self.status == "Activo" and is_expired(self.last_debit_date or self.signature_date):
			self.status = "Caducado"


def is_expired(reference_date) -> bool:
	"""Caducidad por falta de uso (36 meses sin adeudos) **[revisar]**."""
	return bool(reference_date) and getdate(add_months(reference_date, EXPIRY_MONTHS)) < getdate(nowdate())
