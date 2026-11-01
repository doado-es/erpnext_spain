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


VERIFACTU = "VeriFactu"
SII = "SII"


def active_billing_system(company: str | None) -> str | None:
	"""Sistema de registro de facturación activo de la compañía: VeriFactu, SII o
	ninguno (spec 14 §1). Son excluyentes; la validación de Company impide
	activar los dos, pero una escritura que no pase por ella (db.set_value,
	importaciones) podría dejarlos activos a la vez. En ese caso no se trata como
	ninguno de los dos y queda constancia en el Error Log."""
	if not company:
		return None
	values = frappe.get_cached_value(
		"Company", company, ["es_verifactu_enabled", "es_sii_enabled"], as_dict=True
	)
	if not values:
		return None
	verifactu, sii = cint(values.es_verifactu_enabled), cint(values.es_sii_enabled)
	if verifactu and sii:
		frappe.log_error(
			title=f"SII y VeriFactu activos a la vez en {company}",
			message=(
				f"La compañía {company} tiene activados el SII y VeriFactu. No se genera ningún"
				" registro de ninguno de los dos hasta que se desactive uno (Company → pestaña"
				" Spain Compliance)."
			),
		)
		return None
	if verifactu:
		return VERIFACTU
	if sii:
		return SII
	return None


def is_verifactu_active(company: str | None) -> bool:
	return active_billing_system(company) == VERIFACTU


def is_sii_active(company: str | None) -> bool:
	return active_billing_system(company) == SII


# --- Datos sin compañía (terceros, direcciones, artículos) ------------------------
#
# Los clientes, proveedores, direcciones y artículos no son de una compañía: su
# comportamiento español (categoría de impuestos por país, avisos del NIF y del
# nombre, filas de plantillas de impuestos) solo se activa si el sitio tiene alguna
# compañía española con el plan PGC aplicado. Un sitio sin ellas se comporta como
# ERPNext estándar.

SITE_PGC_CACHE_KEY = "erpnext_spain:site_has_pgc_company"
SITE_PGC_CACHE_SECONDS = 300


def site_has_pgc_company() -> bool:
	"""¿Hay en el sitio alguna compañía española con el plan PGC aplicado? En caché
	(se borra al guardar una compañía y caduca a los 5 minutos)."""
	cached = frappe.cache.get_value(SITE_PGC_CACHE_KEY)
	if cached is not None:
		return bool(cached)
	if not frappe.db.has_column("Company", PGC_APPLIED_FIELD):
		return False
	value = bool(frappe.db.exists("Company", {"country": SPAIN, PGC_APPLIED_FIELD: 1}))
	frappe.cache.set_value(SITE_PGC_CACHE_KEY, int(value), expires_in_sec=SITE_PGC_CACHE_SECONDS)
	return value


def clear_site_pgc_cache(doc=None, method: str | None = None) -> None:
	"""doc_event on_update de Company (y al aplicar el plan PGC)."""
	frappe.cache.delete_value(SITE_PGC_CACHE_KEY)


def boot_session(bootinfo) -> None:
	"""El formulario de terceros necesita saber si el sitio es «español»."""
	bootinfo.erpnext_spain_pgc = site_has_pgc_company()
