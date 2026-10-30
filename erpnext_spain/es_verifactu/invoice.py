# Mixin de Sales Invoice para el NAMING de borradores VeriFactu (spec 04 §4).
#
# Se inyecta con el hook `extend_doctype_class`: frappe compone las
# extensiones ANTES del controlador en el MRO (frappe/model/base_document.py
# _get_extended_class), así que el método vive aquí y el SalesInvoice core
# sigue mandando para todo lo demás. El controlador core NO define
# `autoname` (nombra por naming_series), de modo que esta clase es una
# ADICIÓN PURA: no sombrea nada.
#
# Política UNIFORME (spec 04 §4): TODAS las compañías —con VeriFactu activo
# o no— nombran sus borradores con un nombre temporal; el número fiscal solo
# se consume al emitir (el before_submit de emisión.py renombra a la serie
# mapeada). Un solo código, ninguna bifurcación por compañía.
#
# interacción con naming.py (verificada contra fuente v16):
# - set_new_name limpia doc.name salvo import/migración (flags.in_import,
#   naming.py:158) y solo llama run_method("autoname") si el nombre sigue
#   vacío (naming.py:188-189): con nombre explícito este mixin ni corre.
# - el guard `if self.name` cubre además invocaciones programáticas
#   directas al método (defensa total, coste cero).

from __future__ import annotations

import time

import frappe
from frappe.model.naming import make_autoname

# Prefijo del nombre temporal cuando la compañía no tiene patrón configurado.
DRAFT_PREFIX = "BORRADOR-"


class SalesInvoiceVerifactuMixin:
	"""Naming de borradores de Sales Invoice (lote 4b, spec 04 §4)."""

	def autoname(self):
		# Nombre explícito (import/migración/migración de datos): se respeta.
		if self.name:
			return

		pattern = None
		if self.get("company"):
			pattern = frappe.db.get_value("Company", self.company, "es_draft_series")

		if pattern:
			# Patrón propio de la compañía (p. ej. «BORRADOR-.#####»):
			# contador SECUENCIAL propio, jamás compartido con series
			# fiscales (la compuerta de activación valida la no colisión).
			self.name = make_autoname(pattern)
			return

		# Fallback estable y ordenable: epoch (orden temporal) + hash
		# (desambiguación dentro del mismo segundo). No depende de ninguna
		# configuración y no colisiona con series fiscales.
		self.name = f"{DRAFT_PREFIX}{int(time.time())}-{frappe.generate_hash(length=8)}"
