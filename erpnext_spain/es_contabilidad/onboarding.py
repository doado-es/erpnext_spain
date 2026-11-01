# Aplicación automática del plan PGC a las compañías de España (onboarding).
#
# ERPNext no permite registrar planes de cuentas de otras apps en el selector
# del asistente (get_charts_for_country solo lee sus carpetas), así que la
# compañía se crea con el plan estándar y aquí se sustituye por el PGC:
#   - Asistente de configuración: etapa propia (hook setup_wizard_stages) que
#     se ejecuta después de las de ERPNext, con el modelo elegido en la
#     pantalla que añade public/js/setup_wizard.js.
#   - Compañía creada después (formulario, importación, API): after_insert
#     encola la aplicación para después del commit. No se aplica en la misma
#     petición porque ERPNext crea las cuentas estándar en Company.on_update y
#     el formulario quedaría con cuentas por defecto ya borradas.
# Si la compañía no cumple las condiciones (pgc.precondition_error) solo se
# avisa: queda la acción manual «Plan de cuentas → Aplicar plan PGC».

import frappe
from frappe import _

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.utils.gating import SPAIN

DEFAULT_CHART_MODEL = "PYMES"
# Campo de la pantalla del asistente (public/js/setup_wizard.js).
WIZARD_FIELD = "es_chart_model"
NOTICE_EVENT = "erpnext_spain_notice"


# «args» es la firma que impone el asistente de Frappe (overusing-args).
def get_setup_stages(args: dict | None = None) -> list[dict]:  # nosemgrep
	"""Etapas del asistente de configuración (hook setup_wizard_stages)."""
	return [
		{
			"status": _("Aplicando el Plan General Contable"),
			"fail_msg": _("No se ha podido aplicar el Plan General Contable"),
			"tasks": [
				{
					"fn": apply_from_setup_wizard,
					"args": args,
					"fail_msg": _("No se ha podido aplicar el Plan General Contable"),
				}
			],
		}
	]


def apply_from_setup_wizard(args: dict | None) -> None:  # nosemgrep
	"""Aplica el PGC a la compañía que acaba de crear el asistente de ERPNext.

	Sin commit: el asistente confirma la transacción al terminar todas las etapas."""
	args = frappe._dict(args or {})
	if args.country != SPAIN or not args.company_name:
		return
	company = frappe.db.get_value("Company", {"company_name": args.company_name}, "name")
	if not company or pgc.precondition_error(company):
		return
	pgc.apply_pgc_chart(company, chart_model_from(args.get(WIZARD_FIELD)), dry_run=False)


def after_insert(doc, method=None) -> None:
	"""Company.after_insert: encola el PGC para las compañías de España."""
	if doc.country != SPAIN or doc.es_pgc_applied:
		return
	# El asistente lo aplica en su propia etapa, con el modelo elegido.
	if frappe.flags.in_setup_wizard or frappe.flags.in_install or frappe.flags.in_migrate:
		return
	# Los tests crean compañías de España con el plan estándar a propósito.
	if frappe.in_test and not frappe.flags.es_auto_apply_pgc_in_test:
		return

	reason = pgc.precondition_error(doc.name) or permission_error(doc.name)
	if reason:
		frappe.msgprint(
			_("No se ha aplicado el plan PGC automáticamente: {0} Puede aplicarlo después en {1}.").format(
				reason, frappe.bold(_("Plan de cuentas → Aplicar plan PGC"))
			),
			title=_("Plan PGC"),
			indicator="orange",
		)
		return

	frappe.enqueue(
		"erpnext_spain.es_contabilidad.onboarding.apply_in_background",
		queue="long",
		enqueue_after_commit=True,
		company=doc.name,
		chart_model=chart_model_from(doc.get("es_annual_accounts_model")),
	)
	frappe.msgprint(
		_(
			"Se está aplicando el Plan General Contable ({0}) a la compañía. Recibirá un aviso al"
			" terminar; espere antes de registrar operaciones."
		).format(chart_model_from(doc.get("es_annual_accounts_model"))),
		title=_("Plan PGC"),
		indicator="blue",
	)


def apply_in_background(company: str, chart_model: str) -> None:
	"""Trabajo en segundo plano: aplica el PGC y avisa al usuario que creó la compañía.

	Si falla, avisa y relanza la excepción: el trabajo deshace la transacción y
	queda registrado en el log de errores."""
	try:
		pgc.apply_pgc_chart(company, chart_model, dry_run=False)
	except Exception:
		notify(
			_("No se ha podido aplicar el plan PGC a {0}").format(company),
			_("Aplíquelo desde la compañía: Plan de cuentas → Aplicar plan PGC."),
			"red",
		)
		raise
	notify(
		_("Plan PGC aplicado a {0}").format(company),
		_("La compañía ya tiene el plan {0}, sus impuestos y sus cuentas por defecto.").format(chart_model),
		"green",
	)


def chart_model_from(value: str | None) -> str:
	"""Modelo de plan: Normal solo si se pide expresamente; si no, PYMES.

	Igual que el valor por defecto del diálogo manual (public/js/company.js):
	las cuentas anuales Abreviado o PYMES usan el plan PYMES."""
	return "Normal" if value == "Normal" else DEFAULT_CHART_MODEL


def permission_error(company: str) -> str | None:
	try:
		pgc.check_permissions(company)
	except frappe.PermissionError:
		frappe.clear_last_message()
		return _("Su usuario no tiene el rol {0}.").format(
			f" {_('o')} ".join(_(role) for role in pgc.ALLOWED_ROLES)
		)
	return None


def notify(title: str, message: str, indicator: str) -> None:
	frappe.publish_realtime(
		NOTICE_EVENT,
		{"title": title, "message": message, "indicator": indicator},
		user=frappe.session.user,
	)
