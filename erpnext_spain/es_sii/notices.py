# Avisos del SII a los usuarios con los roles de notificación de la compañía.
#
# Tres canales: Notification Log (la campana, siempre), correo (si la compañía
# marca «Avisar por correo») y aviso emergente en el escritorio de los usuarios
# conectados (si marca «Avisar en el escritorio»; evento realtime que pinta
# erpnext_spain/public/js/notices.js). Un fallo de un canal no afecta a los demás
# ni al envío.

import frappe
from frappe import _

REALTIME_EVENT = "erpnext_spain_notice"
GREEN, ORANGE, RED = "green", "orange", "red"


def notify(company: str, subject: str, message: str, indicator: str = ORANGE) -> None:
	from erpnext_spain.es_aeat.utils import notification_users

	users = notification_users(company)
	if not users:
		return
	flags = (
		frappe.get_cached_value(
			"Company", company, ["es_sii_notify_email", "es_sii_notify_desktop"], as_dict=True
		)
		or frappe._dict()
	)
	channels = [_notification_log]
	if flags.es_sii_notify_email:
		channels.append(_email)
	if flags.es_sii_notify_desktop:
		channels.append(_desktop)
	for channel in channels:
		try:
			channel(users, company, subject, message, indicator)
		except Exception:
			frappe.log_error(title=f"SII: fallo avisando a {company}", message=frappe.get_traceback())


def _notification_log(users, company, subject, message, indicator) -> None:
	for user in users:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"document_type": "Company",
				"document_name": company,
				"subject": subject,
				"email_content": message,
			}
		).insert(ignore_permissions=True)


def _email(users, company, subject, message, indicator) -> None:
	emails = frappe.get_all("User", filters={"name": ("in", users), "enabled": 1}, pluck="email")
	if emails:
		frappe.sendmail(recipients=emails, subject=subject, message=message)


def _desktop(users, company, subject, message, indicator) -> None:
	for user in users:
		frappe.publish_realtime(
			REALTIME_EVENT,
			{"title": subject, "message": message, "indicator": indicator},
			user=user,
			after_commit=True,
		)


def notify_results(company: str, counts: dict[str, int]) -> None:
	"""Resultado de un envío: correctos, aceptados con errores e incorrectos."""
	from erpnext_spain.es_sii import outbox

	ok, with_errors, wrong = (
		counts.get(outbox.OK, 0),
		counts.get(outbox.OK_WITH_ERRORS, 0),
		counts.get(outbox.WRONG, 0),
	)
	total = ok + with_errors + wrong
	if not total:
		return
	indicator = RED if wrong else ORANGE if with_errors else GREEN
	notify(
		company,
		_("SII de {0}: {1} registros enviados").format(company, total),
		_("Correctos: {0}. Aceptados con errores: {1}. Incorrectos: {2}.").format(ok, with_errors, wrong),
		indicator,
	)
