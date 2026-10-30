# Tareas programadas de la capa AEAT (spec 13 §2 + §8): aviso diario de
# caducidad de certificados. El drenaje del outbox (cron por minuto) se conecta
# en el lote de VeriFactu, cuando exista su driver.

from __future__ import annotations

import frappe

from erpnext_spain.aeat.utils import (
	EXPIRY_WARNING_DAYS,
	format_aeat_date,
	get_days_remaining,
	notify_roles,
)


def daily() -> None:
	"""Entrada del scheduler_events diario (hooks.py): avisa la caducidad
	próxima de todos los certificados habilitados."""
	notify_certificate_expiry()


def notify_certificate_expiry() -> list[dict]:
	"""Aviso de caducidad de credenciales AEAT (spec 13 §2 + spec 04 §15).

	A 30/7/1 días del fin de vigencia (y el propio día de caducidad) notifica a
	los canales de incidencias de la empresa (roles → Notification Log y
	`es_incidents_email`). La repetición diaria dentro de la ventana de aviso
	es INTENCIONADA (recordatorio diario); mensaje en español con remedio.
	Devuelve lo avisado para trazabilidad/tests.
	"""
	notified: list[dict] = []
	credentials = frappe.get_all(
		"ES AEAT Credential",
		filters={"enabled": 1},
		fields=["name", "company", "purpose", "valid_until"],
		order_by="company asc, purpose asc",
	)

	for credential in credentials:
		days = get_days_remaining(credential.valid_until)
		if days is None or days not in EXPIRY_WARNING_DAYS:
			continue

		if days > 0:
			headline = f"caduca en {days} día{'s' if days != 1 else ''}"
		else:
			headline = "CADUCA HOY"

		notify_roles(
			credential.company,
			f"Certificado AEAT de {credential.company} ({credential.purpose}): {headline}",
			f"El certificado AEAT de la empresa {credential.company} (propósito"
			f" {credential.purpose}, credencial {credential.name}) {headline}"
			f" — vigente hasta el {format_aeat_date(credential.valid_until)}."
			" Remedio: renueve el certificado con su proveedor y actualícelo en"
			" «ES AEAT Credential» ANTES de esa fecha. Al caducar, las remisiones"
			" a la AEAT dejarán de funcionar.",
		)
		notified.append({"credential": credential.name, "company": credential.company, "days": days})

	return notified
