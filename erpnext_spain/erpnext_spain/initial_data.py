# Datos iniciales generales (spec 09 §2 y §3 g): modos de pago españoles,
# festivos nacionales, condiciones de pago, formato de dirección y reglas
# bancarias de partida.
#
# Reglas S1-S7 de la spec 09: funciones ensure_* idempotentes que crean lo que
# falta por un nombre estable y nunca modifican ni borran lo existente.

import frappe
from frappe import _

# --- Modos de pago (S7: se reutilizan los de ERPNext y se añaden estos) -------

EXTRA_MODES_OF_PAYMENT = {
	"Domiciliación bancaria": "Bank",
	"Confirming": "Bank",
	"Bizum": "Phone",
}

# --- Festivos nacionales -------------------------------------------------------
# Fiestas de ámbito nacional (Estatuto de los Trabajadores, art. 37.2, y RD
# 2001/1983). Cada año el BOE publica la relación con los traslados que deciden
# las comunidades autónomas: aquí solo van las fechas comunes a todo el
# territorio. **[revisar]** con la resolución anual del BOE. Se añade un año
# por patch (spec 09 §2).
HOLIDAY_LIST = "Festivos nacionales España"
NATIONAL_HOLIDAYS = {
	2026: [
		("2026-01-01", "Año Nuevo"),
		("2026-01-06", "Epifanía del Señor"),
		("2026-04-03", "Viernes Santo"),
		("2026-05-01", "Fiesta del Trabajo"),
		("2026-08-15", "Asunción de la Virgen"),
		("2026-10-12", "Fiesta Nacional de España"),
		("2026-12-08", "Inmaculada Concepción"),
		("2026-12-25", "Natividad del Señor"),
	],
	2027: [
		("2027-01-01", "Año Nuevo"),
		("2027-01-06", "Epifanía del Señor"),
		("2027-03-26", "Viernes Santo"),
		("2027-10-12", "Fiesta Nacional de España"),
		("2027-11-01", "Todos los Santos"),
		("2027-12-06", "Día de la Constitución Española"),
		("2027-12-08", "Inmaculada Concepción"),
	],
}

# --- Condiciones de pago -------------------------------------------------------
# Ley 3/2004 de morosidad (art. 4): plazo máximo de 60 días naturales entre
# empresas, no ampliable por pacto. Por eso no se crea «30-60-90 días» que
# proponía la spec 09 (decisión del 31/10/2026).
PAYMENT_TERMS = {
	"Contado": 0,
	"30 días": 30,
	"60 días": 60,
}
PAYMENT_TERMS_TEMPLATES = {
	"Contado": [("Contado", 100)],
	"30 días": [("30 días", 100)],
	"60 días": [("60 días", 100)],
	"30-60 días": [("30 días", 50), ("60 días", 50)],
}

# --- Formato de dirección ------------------------------------------------------
ADDRESS_TEMPLATE = """{{ address_line1 }}<br>
{% if address_line2 %}{{ address_line2 }}<br>{% endif -%}
{% if pincode %}{{ pincode }} {% endif %}{{ city }}{% if state and state != city %} ({{ state }}){% endif %}<br>
{{ country }}<br>
{% if phone %}{{ _("Phone") }}: {{ phone }}<br>{% endif -%}
{% if email_id %}{{ _("Email") }}: {{ email_id }}<br>{% endif -%}
"""

# --- Reglas bancarias de partida (spec 09 §3 g, spec 13) ------------------------
# Comisiones e intereses de los extractos (Norma 43, concepto común 17). Prioridad
# baja para que las reglas del usuario ganen.
BANK_RULES = (
	{
		"rule_name": "Comisiones bancarias",
		"transaction_type": "Withdrawal",
		"contains": ("COMISION", "COMISIÓN"),
		"account": "6260",
		"rule_description": "Comisiones y gastos de los extractos bancarios (Norma 43, concepto 17).",
	},
	{
		"rule_name": "Intereses bancarios pagados",
		"transaction_type": "Withdrawal",
		"contains": ("INTERES", "INTERÉS"),
		"account": "6623",
		"rule_description": "Intereses de préstamos y descubiertos cargados por el banco.",
	},
	{
		"rule_name": "Intereses bancarios cobrados",
		"transaction_type": "Deposit",
		"contains": ("INTERES", "INTERÉS"),
		"account": "7690",
		"rule_description": "Intereses de cuentas y depósitos abonados por el banco.",
	},
)
BANK_RULE_PRIORITY = 100


def ensure_global_records() -> dict[str, list[str]]:
	return {
		"Mode of Payment": ensure_modes_of_payment(),
		"Holiday List": ensure_holiday_list(),
		"Payment Terms Template": ensure_payment_terms(),
		"Address Template": ensure_address_template(),
	}


def ensure_modes_of_payment() -> list[str]:
	created = []
	for name, kind in EXTRA_MODES_OF_PAYMENT.items():
		if not frappe.db.exists("Mode of Payment", name):
			frappe.get_doc(
				{"doctype": "Mode of Payment", "mode_of_payment": name, "type": kind, "enabled": 1}
			).insert(ignore_permissions=True)
			created.append(name)
	return created


def ensure_holiday_list() -> list[str]:
	"""Crea la lista o le añade los años que falten (sin tocar los existentes)."""
	years = sorted(NATIONAL_HOLIDAYS)
	if not frappe.db.exists("Holiday List", HOLIDAY_LIST):
		doc = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": HOLIDAY_LIST,
				"from_date": f"{years[0]}-01-01",
				"to_date": f"{years[-1]}-12-31",
				"holidays": [
					{"holiday_date": date, "description": name, "weekly_off": 0}
					for year in years
					for date, name in NATIONAL_HOLIDAYS[year]
				],
			}
		)
		doc.insert(ignore_permissions=True)
		return [HOLIDAY_LIST]

	doc = frappe.get_doc("Holiday List", HOLIDAY_LIST)
	present = {str(row.holiday_date)[:4] for row in doc.holidays}
	missing = [year for year in years if str(year) not in present and f"{year}-12-31" > str(doc.to_date)]
	if not missing:
		return []
	doc.to_date = max(str(doc.to_date), f"{missing[-1]}-12-31")
	for year in missing:
		for date, name in NATIONAL_HOLIDAYS[year]:
			doc.append("holidays", {"holiday_date": date, "description": name, "weekly_off": 0})
	doc.save(ignore_permissions=True)
	return [f"{HOLIDAY_LIST} {year}" for year in missing]


def ensure_payment_terms() -> list[str]:
	for name, days in PAYMENT_TERMS.items():
		if not frappe.db.exists("Payment Term", name):
			frappe.get_doc(
				{
					"doctype": "Payment Term",
					"payment_term_name": name,
					"due_date_based_on": "Day(s) after invoice date",
					"credit_days": days,
					"invoice_portion": 100,
				}
			).insert(ignore_permissions=True)

	created = []
	for name, terms in PAYMENT_TERMS_TEMPLATES.items():
		if frappe.db.exists("Payment Terms Template", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": name,
				"terms": [
					{
						"payment_term": term,
						"invoice_portion": portion,
						"due_date_based_on": "Day(s) after invoice date",
						"credit_days": PAYMENT_TERMS[term],
					}
					for term, portion in terms
				],
			}
		).insert(ignore_permissions=True)
		created.append(name)
	return created


def ensure_address_template() -> list[str]:
	"""Formato español para el país Spain.

	El asistente de configuración crea la plantilla del país del sistema con el
	formato genérico de Frappe [verificado v16.50]. Se sustituye solo si sigue
	siendo ese genérico; si el usuario la cambió, se respeta (S2)."""
	if not frappe.db.exists("Country", "Spain"):
		return []
	current = frappe.db.get_value("Address Template", "Spain", "template")
	if current is None:
		frappe.get_doc(
			{"doctype": "Address Template", "country": "Spain", "template": ADDRESS_TEMPLATE}
		).insert(ignore_permissions=True)
		return ["Spain"]
	if current.strip() == frappe_default_address_template().strip():
		frappe.db.set_value("Address Template", "Spain", "template", ADDRESS_TEMPLATE)
		return ["Spain"]
	return []


def frappe_default_address_template() -> str:
	path = frappe.get_app_path("frappe", "contacts", "doctype", "address_template", "address_template.jinja")
	with open(path, encoding="utf-8") as template:
		return template.read()


def setup_company(company: str, chart_model: str | None = None) -> list[str]:
	"""Paso de «Aplicar plan PGC»: reglas bancarias de partida de la compañía."""
	ensure_global_records()
	return ensure_bank_rules(company)


def ensure_bank_rules(company: str) -> list[str]:
	created = []
	for spec in BANK_RULES:
		rule_name = f"{spec['rule_name']} - {frappe.get_cached_value('Company', company, 'abbr')}"
		if frappe.db.exists("Bank Transaction Rule", rule_name):
			continue
		account = frappe.db.get_value(
			"Account", {"company": company, "account_number": spec["account"]}, "name"
		)
		if not account:
			continue
		frappe.get_doc(
			{
				"doctype": "Bank Transaction Rule",
				"rule_name": rule_name,
				"company": company,
				"transaction_type": spec["transaction_type"],
				"classify_as": "Bank Entry",
				"bank_entry_type": "Single Account",
				"account": account,
				"priority": BANK_RULE_PRIORITY,
				"rule_description": _(spec["rule_description"]),
				"description_rules": [{"check": "Contains", "value": value} for value in spec["contains"]],
			}
		).insert(ignore_permissions=True)
		created.append(rule_name)
	return created
