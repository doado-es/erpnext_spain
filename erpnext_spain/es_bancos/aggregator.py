# Conexión con agregadores de información de cuentas (PSD2) (spec 13 §3).
#
# La compañía no habla con cada banco: se integra con un agregador con licencia
# de proveedor de servicios de información sobre cuentas (decisión A8, pendiente).
# Todos los agregadores implementan la misma interfaz; cambiar de proveedor solo
# cambia el adaptador. Hoy solo existe el adaptador «Simulado» (pruebas).

from dataclasses import dataclass
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

SIMULATED = "Simulado"


@dataclass
class AggregatorTransaction:
	transaction_id: str
	date: date
	amount: float  # positivo = abono
	description: str
	reference: str = ""
	party_name: str = ""
	party_iban: str = ""


class AggregatorAdapter:
	"""Interfaz común de los agregadores."""

	def __init__(self, settings):
		self.settings = settings

	def start_consent(self, bank_account: str) -> dict:
		"""Devuelve {"redirect_url": ..., "consent_id": ...}."""
		raise NotImplementedError

	def renew_consent(self, bank_account: str) -> dict:
		raise NotImplementedError

	def get_transactions(
		self, bank_account: str, from_date: date, to_date: date
	) -> list[AggregatorTransaction]:
		raise NotImplementedError

	def get_balance(self, bank_account: str) -> float:
		raise NotImplementedError


class SimulatedAdapter(AggregatorAdapter):
	"""Agregador de pruebas: los movimientos los fija el test en
	`frappe.flags.es_simulated_transactions[bank_account]`."""

	def start_consent(self, bank_account: str) -> dict:
		return {"redirect_url": "/app/bank-account/" + bank_account, "consent_id": f"SIM-{bank_account}"}

	renew_consent = start_consent

	def get_transactions(self, bank_account, from_date, to_date):
		data = (frappe.flags.es_simulated_transactions or {}).get(bank_account, [])
		return [t for t in data if getdate(from_date) <= getdate(t.date) <= getdate(to_date)]

	def get_balance(self, bank_account):
		return sum(t.amount for t in (frappe.flags.es_simulated_transactions or {}).get(bank_account, []))


ADAPTERS = {SIMULATED: SimulatedAdapter}


def adapter_for(aggregator: str) -> AggregatorAdapter:
	settings = frappe.get_doc("ES Bank Aggregator", aggregator)
	if not settings.enabled:
		frappe.throw(_("El agregador {0} está desactivado.").format(frappe.bold(aggregator)))
	adapter = ADAPTERS.get(settings.provider)
	if not adapter:
		frappe.throw(
			_("El proveedor {0} aún no tiene adaptador. Hoy solo está disponible el simulado.").format(
				settings.provider
			)
		)
	return adapter(settings)


def sync_bank_account(bank_account: str) -> int:
	"""Crea los movimientos nuevos de una cuenta conectada. Devuelve cuántos."""
	account = frappe.get_doc("Bank Account", bank_account)
	if not account.get("es_bank_aggregator") or not account.integration_id:
		return 0
	adapter = adapter_for(account.es_bank_aggregator)
	from_date = (
		getdate(account.last_integration_date)
		if account.last_integration_date
		else getdate(add_days(nowdate(), -90))
	)
	currency = frappe.get_cached_value("Company", account.company, "default_currency")
	created = 0
	for tx in adapter.get_transactions(bank_account, add_days(from_date, -3), getdate(nowdate())):
		tid = f"AGG-{tx.transaction_id}"
		if frappe.db.exists(
			"Bank Transaction", {"transaction_id": tid, "bank_account": bank_account, "docstatus": ["<", 2]}
		):
			continue
		amount = flt(tx.amount)
		doc = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"date": tx.date,
				"company": account.company,
				"bank_account": bank_account,
				"currency": currency,
				"deposit": amount if amount > 0 else 0,
				"withdrawal": -amount if amount < 0 else 0,
				"description": tx.description,
				"reference_number": tx.reference,
				"transaction_id": tid,
				"bank_party_name": tx.party_name,
				"bank_party_iban": tx.party_iban,
			}
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		created += 1
	account.db_set("last_integration_date", now_datetime())
	return created


def sync_all() -> None:
	"""Job programado: sincroniza las cuentas conectadas a un agregador activo."""
	for name in frappe.get_all(
		"Bank Account",
		filters={"es_bank_aggregator": ["is", "set"], "integration_id": ["is", "set"], "disabled": 0},
		pluck="name",
	):
		try:
			sync_bank_account(name)
		except Exception:
			frappe.log_error(title=_("Sincronización bancaria de {0}").format(name))


def warn_expiring_consents() -> None:
	"""Job diario: avisa 7 días antes de que caduque el consentimiento."""
	limit = add_days(nowdate(), 7)
	for name, expiry in frappe.get_all(
		"Bank Account",
		filters={"es_consent_expiry": ["between", [nowdate(), limit]]},
		fields=["name", "es_consent_expiry"],
		as_list=True,
	):
		for user in frappe.get_all(
			"Has Role", filters={"role": "Accounts Manager", "parenttype": "User"}, pluck="parent"
		):
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": user,
					"type": "Alert",
					"document_type": "Bank Account",
					"document_name": name,
					"subject": _("El consentimiento bancario de {0} caduca el {1}: renuévelo.").format(
						name, expiry
					),
				}
			).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def start_consent(bank_account: str) -> dict:
	"""Inicia el consentimiento con el agregador de la cuenta."""
	account = frappe.get_doc("Bank Account", bank_account)
	account.check_permission("write")
	if not account.get("es_bank_aggregator"):
		frappe.throw(_("Elija el agregador en la cuenta bancaria."))
	consent = adapter_for(account.es_bank_aggregator).start_consent(bank_account)
	days = frappe.db.get_value("ES Bank Aggregator", account.es_bank_aggregator, "consent_days") or 180
	account.db_set({"integration_id": consent["consent_id"], "es_consent_expiry": add_days(nowdate(), days)})
	return {"redirect_url": consent["redirect_url"]}
