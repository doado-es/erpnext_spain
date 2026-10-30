# Utilidades transversales de la capa AEAT (spec 13 §7): huso horario
# Europe/Madrid y formatos AEAT (único punto de verdad), permisos explícitos
# por empresa+propósito para llamadas whitelisted (doc 12 §18) y notificaciones
# a roles por los DOS canales de incidencias (spec 04 §9: Notification Log
# in-app + email externo `es_incidents_email` de la Company).

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils.user import get_system_managers

MADRID_TZ = ZoneInfo("Europe/Madrid")

# Días de antelación (y el propio día de caducidad) en los que el scheduler
# diario avisa la expiración de un certificado (spec 13 §2 + spec 04 §15).
EXPIRY_WARNING_DAYS = (30, 7, 1, 0)


def absolute_site_path(*parts: str) -> str:
	"""Ruta ABSOLUTA del site actual, INDEPENDIENTE del CWD del proceso.

	Ancla: frappe.utils.get_bench_path() (basado en frappe.__file__ — o en
	FRAPPE_BENCH_ROOT —, nunca en el CWD) + frappe.local.site. Por qué: los
	workers del planificador/web corren con CWDs MIXTOS (raíz del bench y
	sites/) y frappe.get_site_path() devuelve rutas RELATIVAS al CWD — con
	PEM de TLS mutua eso revienta con OSError según el proceso que caiga,
	y con el cerrojo de cadena cada CWD usaría un ARCHIVO DISTINTO (el
	cerrojo dejaría de excluir). Todo path de site que abramos con open()
	o FileLock debe salir de aquí.
	"""
	from frappe.utils import get_bench_path

	return os.path.join(get_bench_path(), "sites", frappe.local.site, *parts)


def now_aeat() -> datetime:
	"""Ahora, consciente de zona, en huso Europe/Madrid (+01:00 invierno / +02:00 verano)."""
	return datetime.now(MADRID_TZ)


def to_madrid(moment: datetime) -> datetime:
	"""Normaliza un datetime a Europe/Madrid; los naive se asumen ya en Madrid."""
	if moment.tzinfo is None:
		return moment.replace(tzinfo=MADRID_TZ)
	return moment.astimezone(MADRID_TZ)


def format_aeat_datetime(moment: datetime | None = None) -> str:
	"""Timestamp AEAT: ISO 8601 con offset explícito tipo +01:00, sin microsegundos.

	Ejemplo: 2026-01-30T13:58:26+01:00. Es el formato de FechaHoraHusoGenRegistro y
	DatosPresentacion del esquema VeriFactu.
	"""
	if moment is None:
		moment = now_aeat()
	return to_madrid(moment).isoformat(timespec="seconds")


def format_aeat_date(value: date | datetime | str | None = None) -> str:
	"""Fecha AEAT dd-mm-aaaa (FechaExpedicionFactura, etc.).

	Acepta date/datetime y TAMBIÉN str ISO-8601 «YYYY-MM-DD» — frappe entrega
	los Date de esa forma cuando el valor viene de una asignación en memoria
	(p. ej. posting_date fijado en un hook) — y los normaliza al mismo
	formato congelado dd-mm-aaaa que consume el adaptador puro
	(es_verifactu.utils.data_adapter._format_date).
	"""
	if value is None:
		value = now_aeat().date()
	elif isinstance(value, datetime):
		value = to_madrid(value).date()
	elif isinstance(value, str):
		value = datetime.strptime(value, "%Y-%m-%d").date()
	return value.strftime("%d-%m-%Y")


def get_days_remaining(valid_until: date | str | None) -> int | None:
	"""Días que faltan hasta `valid_until` (negativos si ya caducó); None sin fecha."""
	if not valid_until:
		return None
	if isinstance(valid_until, str):
		valid_until = frappe.utils.getdate(valid_until)
	return (valid_until - frappe.utils.getdate(now_aeat().date())).days


def _notification_roles(company: str) -> list[str]:
	"""Roles destinatarios de incidencias de la empresa: los configurados en el
	tab «Spain Compliance» de la Company (child table «ES Verifactu Notification
	Role», lote VeriFactu). Hasta que exista (fallback documentado): System
	Managers, que siempre deben enterarse de las incidencias de compliance."""
	if frappe.db.exists("DocType", "ES Verifactu Notification Role"):
		roles = frappe.get_all(
			"ES Verifactu Notification Role",
			filters={
				"parent": company,
				"parenttype": "Company",
				"parentfield": "es_verifactu_notification_roles",
			},
			pluck="role",
		)
		if roles:
			return list(dict.fromkeys(roles))
	return ["System Manager"]


def _roles_with_permission(company: str) -> set[str]:
	"""Roles con permiso AEAT sobre la empresa (spec 13 §7). Mientras la child
	table de roles no esté configurada, fallback: Accounts Manager (equipo
	contable que opera las remisiones en producción). System Manager se comprueba
	aparte y SIEMPRE tiene permiso."""
	if frappe.db.exists("DocType", "ES Verifactu Notification Role"):
		roles = set(
			frappe.get_all(
				"ES Verifactu Notification Role",
				filters={
					"parent": company,
					"parenttype": "Company",
					"parentfield": "es_verifactu_notification_roles",
				},
				pluck="role",
			)
		)
		if roles:
			return roles
	return {"Accounts Manager"}


def has_aeat_permission(
	user: str | None = None, company: str | None = None, purpose: str | None = None
) -> bool:
	"""Permiso explícito por empresa+propósito para TODA llamada whitelisted que
	dispare comunicación con la AEAT (doc 12 §18): el chequeo considera de qué
	Company/certificado se trata, no solo un rol genérico.

	Se concede si:
	1. El usuario es Administrator o tiene rol System Manager; o
	2. Existe credencial HABILITADA para (company, purpose) — sin certificado no
	   hay nada que autorizar — y el usuario tiene un rol con permiso sobre esa
	   empresa (roles de notificación configurados o, en su defecto, Accounts
	   Manager) y acceso de lectura a la Company.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	user_roles = set(frappe.get_roles(user))
	if "System Manager" in user_roles:
		return True

	if not company or not purpose:
		return False

	if not frappe.db.exists("ES AEAT Credential", {"company": company, "purpose": purpose, "enabled": 1}):
		return False

	if user_roles & _roles_with_permission(company):
		return bool(frappe.has_permission("Company", "read", doc=company, user=user))

	return False


def _users_with_roles(roles: list[str]) -> list[str]:
	"""Usuarios habilitados con alguno de los roles dados (deduplicados)."""
	if not roles:
		return []
	return list(
		dict.fromkeys(
			frappe.get_all(
				"Has Role",
				filters={"parenttype": "User", "role": ("in", roles)},
				pluck="parent",
			)
		)
	)


def notify_roles(company: str, subject: str, message: str, roles: list[str] | None = None) -> None:
	"""Notifica una incidencia de compliance de la empresa por los DOS canales
	(spec 04 §9):

	1. Notification Log (in-app) para los usuarios con los roles dados
	   (roles=None → roles de notificación de la empresa; fallback System
	   Managers).
	2. Email externo al `es_incidents_email` de la Company (p. ej. asesor
	   fiscal), si está configurado.

	Aislamiento de canales: un fallo de un canal se registra con log_error y
	NUNCA rompe el otro canal ni al llamante (el manager drena en bucle).
	"""
	if roles is None:
		roles = _notification_roles(company)

	users = _users_with_roles(roles)
	if not users:
		users = get_system_managers(only_name=True)

	if users:
		try:
			_notification_log_channel(users, company, subject, message)
		except Exception:
			frappe.log_error(
				title=f"AEAT: fallo notificando (Notification Log) a {company}",
				message=frappe.get_traceback(),
			)

	try:
		_incidents_email_channel(company, subject, message)
	except Exception:
		frappe.log_error(
			title=f"AEAT: fallo notificando por email de incidencias a {company}",
			message=frappe.get_traceback(),
		)


def _notification_log_channel(users: list[str], company: str, subject: str, message: str) -> None:
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	# enqueue_create_notification resuelve destinatarios por EMAIL
	# (make_notification_logs matchea User.email): los roles devuelven NOMBRES
	# de usuario («Administrator» cuyo email es otro) — se traducen aquí o la
	# notificación in-app se pierde silenciosamente.
	emails = frappe.get_all("User", filters={"name": ("in", users), "enabled": 1}, pluck="email")
	enqueue_create_notification(
		emails,
		{
			"type": "Alert",
			"document_type": "Company",
			"document_name": company,
			"subject": subject,
			"email_content": message,
		},
	)


def _incidents_email_channel(company: str, subject: str, message: str) -> None:
	email = frappe.db.get_value("Company", company, "es_incidents_email")
	if not email:
		return
	frappe.sendmail(recipients=[email], subject=subject, message=message, delayed=True)
