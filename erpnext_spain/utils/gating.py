# Activación por compañía (maestro R7, spec 01 §5).
#
# Todo doc_event, regional override y endpoint de la app llama a una de estas
# funciones como PRIMERA instrucción y sale si devuelve False: una compañía sin
# la activación correspondiente se comporta exactamente como ERPNext estándar.
#
# Rendimiento (R4): solo frappe.get_cached_value (caché de documento de
# Company, que Frappe invalida al guardar o al hacer db.set_value). Nada de
# consultas a la base de datos por llamada.

from __future__ import annotations

import frappe
from frappe.utils import cint

SPAIN = "Spain"
PGC_APPLIED_FIELD = "es_pgc_applied"


def is_pgc_company(company: str | None) -> bool:
	"""True solo si la compañía es de España y tiene el plan PGC aplicado.

	Devuelve False sin error si la compañía no existe o si los campos de la
	app aún no están creados (instalación a medias)."""
	if not company:
		return False
	values = frappe.get_cached_value("Company", company, ["country", PGC_APPLIED_FIELD], as_dict=True)
	if not values:
		return False
	return values.country == SPAIN and bool(cint(values.get(PGC_APPLIED_FIELD)))


def is_feature_enabled(company: str | None, flag: str) -> bool:
	"""True si la compañía tiene activado el ajuste ``flag`` de una funcionalidad
	(p. ej. ``es_verifactu_enabled`` o ``es_fiscal_numbering``).

	Solo admite campos propios de la app (prefijo ``es_``), para que no se use
	por error con campos de ERPNext. Devuelve False sin error si la compañía no
	existe o el campo aún no está creado."""
	if not flag.startswith("es_"):
		raise ValueError(f"is_feature_enabled solo admite campos de la app (es_*), no «{flag}».")
	if not company:
		return False
	return bool(cint(frappe.get_cached_value("Company", company, flag)))
