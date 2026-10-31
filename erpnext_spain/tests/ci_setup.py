# Preparación del sitio de tests del CI (spec 01 §7).
#
# Un sitio recién creado no ha pasado el asistente de configuración: no hay
# unidades de medida, grupos, ejercicio fiscal ni país del sistema. Esta
# función lo completa con datos españoles, como el sitio de tests local
# (test.es.localhost). Solo para el CI y sitios de tests (`bench execute`
# confirma la transacción al terminar):
#   bench --site <sitio> execute erpnext_spain.tests.ci_setup.complete_setup

from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate


def complete_setup() -> None:
	"""Completa el asistente de configuración si no se ha hecho. Idempotente."""
	if frappe.is_setup_complete():
		return

	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	year = getdate(nowdate()).year
	setup_complete(
		{
			"language": "English",
			"country": "Spain",
			"timezone": "Europe/Madrid",
			"currency": "EUR",
			"full_name": "Test Administrator",
			"email": "test-admin@example.com",
			"password": "test-admin",
			"company_name": "_Test Setup Company ES",
			"company_abbr": "_TSCE",
			"chart_of_accounts": "Standard",
			"fy_start_date": f"{year}-01-01",
			"fy_end_date": f"{year}-12-31",
			"setup_demo": 0,
		}
	)
