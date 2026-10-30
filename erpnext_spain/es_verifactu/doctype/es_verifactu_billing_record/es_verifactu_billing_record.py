# Libro de registros de facturación «ES Verifactu Billing Record» (spec 04 §2.2).
#
# Doctype INDEPENDIENTE (no child table de la factura): el libro debe sobrevivir
# a cualquier operación sobre la factura (integridad legal de la cadena), las
# queries de subsanación/orden de cadena operan sin cargar facturas, y tiene
# permisos propios.
#
# Máquina de estados (spec 04 §3): creación → PendienteEnvio. Los estados
# terminales (Correcto / AceptadoConErrores / Incorrecto) SOLO los transiciona
# el procesador de respuestas de la AEAT (lote de remisión), que lo hace con
# el flag `flags.es_verifactu_procesador_respuestas = True`. Toda otra edición
# directa de un registro en estado terminal se rechaza con remedio (libro
# inmutable). La subsanación NUNCA edita: crea un registro nuevo con el flag
# `is_correction`.

from __future__ import annotations

import frappe
from frappe.model.document import Document

LEDGER_DOCTYPE = "ES Verifactu Billing Record"

PENDING_SEND_STATE = "PendienteEnvio"
TERMINAL_STATES = ("Correcto", "AceptadoConErrores", "Incorrecto")

# Flag que habilita al procesador de respuestas (lote de remisión) a crear en
# estado terminal o a transicionar registros ya terminales. Nadie más lo fija.
RESPONSE_PROCESSOR_FLAG = "es_verifactu_procesador_respuestas"


class ESVerifactuBillingRecord(Document):
	def validate(self):
		self._guard_born_pending()
		self._guard_terminal_immutability()

	def _guard_born_pending(self) -> None:
		"""Un registro NACE en PendienteEnvio (spec 04 §3): solo el procesador
		de respuestas puede fijar un estado terminal ya en la creación."""
		if self.is_new() and self.status != PENDING_SEND_STATE:
			if not self.flags.get(RESPONSE_PROCESSOR_FLAG):
				frappe.throw(
					f"El registro de facturación {self.name or '(nuevo)'} no puede crearse en"
					f" estado «{self.status}»: todo registro nace en «{PENDING_SEND_STATE}»"
					" y solo el procesador de respuestas de la AEAT transiciona estados"
					" (spec 04 §3). Remedio: cree el registro sin estado (nace PendienteEnvio)"
					" y deje que la respuesta de la AEAT lo transicione.",
					frappe.ValidationError,
				)

	def _guard_terminal_immutability(self) -> None:
		"""Congelación de terminales (spec 04 §2.2/§3): tras Correcto /
		AceptadoConErrores / Incorrecto, el registro queda congelado — solo el
		procesador de respuestas (flag) puede volver a tocarlo."""
		if self.is_new():
			return

		previous = frappe.db.get_value(self.doctype, self.name, "status")
		if previous in TERMINAL_STATES and not self.flags.get(RESPONSE_PROCESSOR_FLAG):
			frappe.throw(
				f"El registro de facturación {self.name} está en estado terminal"
				f" «{previous}» y queda congelado: el libro de registros es inmutable"
				" y solo el procesador de respuestas de la AEAT puede transicionar"
				" estados (spec 04 §2.2/§3). Remedio: para corregir un registro"
				" rechazado use la subsanación (crea un registro NUEVO encadenado con"
				" el indicador «Subsanación»); para anular una factura aceptada use la"
				" cancelación, que genera su RegistroAnulación.",
				frappe.ValidationError,
			)

	def on_doctype_update(self) -> None:
		# Índices del libro (queries de cadena y outbox, spec 04 §2.2/§8) vía la
		# API del framework (doc 12 §19: no SQL crudo).
		frappe.db.add_index(LEDGER_DOCTYPE, ["company", "chain_index"])
		frappe.db.add_index(LEDGER_DOCTYPE, ["status"])


def has_records(company: str) -> bool:
	"""Si la empresa tiene ALGÚN registro de facturación (congela la fecha de
	activación — spec 04 §2.1)."""
	return bool(frappe.db.exists(LEDGER_DOCTYPE, {"company": company}))


def pending_send_count(company: str) -> int:
	"""Nº de registros del outbox de la empresa (aviso de desactivación, UX
	spec 04 §2.1/§15)."""
	return frappe.db.count(LEDGER_DOCTYPE, {"company": company, "status": PENDING_SEND_STATE})
