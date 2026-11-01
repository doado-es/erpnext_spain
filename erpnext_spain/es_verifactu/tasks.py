# Tareas de remisión VeriFactu (spec 04 §8): drenaje del outbox + alerta de
# outbox estancado.
#
# - `send_pending(company)`: remisión Inmediata — la encola on_submit
#   con enqueue_after_commit (JAMÁS antes del commit del submit); drena SOLO
#   esa empresa.
# - `drain_outbox()`: entrada del planificador (cron por minuto, hooks.py)
#   — drena todas las empresas con pendientes, SIN gate de «activada» (spec
#   04 §8: lo pendiente al desactivar sigue remitiéndose) y con aislamiento
#   total de errores por empresa en el manager (spec 13 §5).
# - `daily()`: alerta de outbox ESTANCADO (spec 04 §8) — registros
#   PendienteEnvio que llevan más de STALE_OUTBOX_HOURS sin moverse
#   (por defecto 24 h): con remisión diferida la ventana legal es corta, un
#   outbox parado es una INCIDENCIA, no un estado silencioso. La repetición
#   diaria del aviso es INTENCIONADA (recordatorio).

from __future__ import annotations

import frappe

from erpnext_spain.es_aeat.manager import AEATOutboxManager
from erpnext_spain.es_aeat.utils import notify_roles
from erpnext_spain.es_verifactu.driver import VerifactuDriver

LEDGER_DOCTYPE = "ES Verifactu Billing Record"
PENDING_SEND_STATE = "PendienteEnvio"

# Ventana (horas) tras la que un registro PendienteEnvio se considera
# estancado (spec 04 §8: configurable, default 24).
STALE_OUTBOX_HOURS_DEFAULT = 24


def send_pending(company: str) -> None:
	"""Drenaje del outbox de UNA empresa (remisión Inmediata, spec 04 §8):
	remite a la AEAT sus registros «PendienteEnvio», procesa la respuesta y
	actualiza los estados del libro y de las facturas."""
	AEATOutboxManager().drain_company(VerifactuDriver(), company)


def drain_outbox() -> None:
	"""Drenaje del outbox de TODAS las empresas con pendientes (scheduler,
	cron por minuto): el driver filtra por PendienteEnvio y el manager
	aísla los errores por empresa."""
	AEATOutboxManager().drain([VerifactuDriver()])


def daily() -> None:
	"""Entrada del scheduler diario (hooks.py, spec 04 §8): alerta del
	outbox estancado de TODAS las empresas con pendientes parados."""
	alert_stale_outbox()


def alert_stale_outbox(hours: int = STALE_OUTBOX_HOURS_DEFAULT) -> list[dict]:
	"""Alerta de outbox estancado (spec 04 §8): registros «PendienteEnvio»
	que llevan más de `hours` SIN tocar su `modified` (ni el drenaje ni
	ningún otro proceso los movió) → incidencia por los DOS canales de la
	empresa (roles → Notification Log + `es_incidents_email`), en español
	y con remedio (revisar la salud del scheduler/manager). Devuelve lo
	avisado para trazabilidad/tests; la repetición diaria es el
	recordatorio intencionado (idempotencia no requerida)."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-hours)
	stale = frappe.get_all(
		LEDGER_DOCTYPE,
		filters={"status": PENDING_SEND_STATE, "modified": ("<", cutoff)},
		fields=["name", "company", "sales_invoice", "chain_index"],
		order_by="company asc, chain_index asc",
	)

	by_company: dict[str, list] = {}
	for record in stale:
		by_company.setdefault(record.company, []).append(record)

	alerted: list[dict] = []
	for company, records in by_company.items():
		refs = ", ".join(
			f"{r.name} (factura {r.sales_invoice or '(sin factura)'}, cadena {r.chain_index})"
			for r in records
		)
		notify_roles(
			company,
			f"VeriFactu: outbox de {company} estancado"
			f" ({len(records)} registro{'s' if len(records) != 1 else ''} sin remitir)",
			f"La empresa {company} tiene {len(records)} registros de facturación"
			" en estado «PendienteEnvio» que llevan más de"
			f" {hours} horas sin remitirse a la AEAT: {refs}. Con remisión"
			" diferida la ventana legal es corta: un outbox parado"
			" es una incidencia, no un estado silencioso. Remedio: verifique la"
			" salud del planificador (scheduler jobs del bench), la conectividad"
			" con la AEAT y la credencial en «ES AEAT Credential»; los registros"
			" seguirán intentándose en cada corrida del drenaje (cron por minuto),"
			" y este aviso se repetirá a diario mientras el outbox siga parado.",
		)
		alerted.append({"company": company, "records": [record.name for record in records]})

	return alerted
