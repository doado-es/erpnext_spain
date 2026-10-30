# Nombre de los borradores de Sales Invoice (spec 04 §4 del código base;
# correcciones H1 y H2 de la spec 01 §8).
#
# Con la numeración al emitir, el borrador recibe un nombre temporal y el número
# fiscal solo se consume al validar (emission.before_submit renombra a la serie
# del tipo de factura). Esa numeración solo se aplica en las compañías que la
# tienen activa; en las demás el autoname no asigna nombre y Frappe sigue con la
# naming_series de la factura, como en ERPNext estándar (R7).
#
# Se engancha como doc_event «autoname» y no como extensión de la clase (H2,
# R2): set_new_name llama a doc.run_method("autoname") si el documento aún no
# tiene nombre, y run_method ejecuta los doc_events aunque el controlador no
# defina el método [verificado en Frappe v16, model/naming.py].

from __future__ import annotations

import re
import time

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from erpnext_spain.utils.gating import is_feature_enabled

# Prefijo del nombre temporal cuando la compañía no tiene patrón configurado.
DRAFT_PREFIX = "BORRADOR-"


def uses_draft_naming(company: str | None) -> bool:
	"""¿Numera la compañía al emitir? Hoy, solo con VeriFactu activo. La spec 05
	§1 lo extenderá a es_fiscal_numbering, independiente de VeriFactu, cuando el
	renombrado a la serie fiscal deje de depender de VeriFactu."""
	return is_feature_enabled(company, "es_verifactu_enabled")


def autoname(doc: Document, method: str | None = None) -> None:
	"""doc_event autoname de Sales Invoice: nombre temporal del borrador."""
	# Nombre explícito (importación, migración): se respeta.
	if doc.name or not uses_draft_naming(doc.get("company")):
		return

	pattern = frappe.get_cached_value("Company", doc.company, "es_draft_series")
	if pattern:
		# Patrón propio de la compañía (p. ej. «BORRADOR-.#####»): contador
		# secuencial propio, nunca compartido con las series fiscales (la
		# activación de VeriFactu valida que no colisionen).
		doc.name = make_autoname(pattern)
		return

	# Fallback estable y ordenable: epoch + hash, sin depender de configuración.
	doc.name = f"{DRAFT_PREFIX}{int(time.time())}-{frappe.generate_hash(length=8)}"


def is_draft_name(name: str | None, draft_pattern: str | None) -> bool:
	"""¿El nombre es un nombre temporal nuestro? El literal «BORRADOR-» cubre el
	fallback; el prefijo del patrón de la compañía, su serie propia."""
	if not name:
		return False
	if name.startswith(DRAFT_PREFIX):
		return True
	if draft_pattern:
		prefix = re.split(r"[.#]", draft_pattern, maxsplit=1)[0]
		if prefix and name.startswith(prefix):
			return True
	return False


def release_draft_name(doc: Document, method: str | None = None) -> None:
	"""doc_event before_submit: si un borrador con nombre temporal se valida en una
	compañía que ya no numera al emitir (p. ej. se desactivó VeriFactu con
	borradores pendientes), recibe el número de su naming_series. Sin esto se
	quedaría con el nombre temporal para siempre (H1)."""
	if uses_draft_naming(doc.company):
		return
	pattern = frappe.get_cached_value("Company", doc.company, "es_draft_series")
	if not is_draft_name(doc.name, pattern):
		return
	series = doc.get("naming_series")
	if not series:
		field = frappe.get_meta("Sales Invoice").get_field("naming_series")
		series = field.default or (field.options or "").split("\n")[0]
	new_name = make_autoname(series, doc=doc)
	frappe.rename_doc("Sales Invoice", doc.name, new_name, force=True, show_alert=False, rebuild_search=False)
	doc.name = new_name
	doc.set_parent_in_children()
