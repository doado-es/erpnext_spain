# Site tests de la integración notify_roles ↔ roles de notificación de la
# Company (spec 04 §9 + spec 13 §7): con roles=None, notify_roles resuelve
# las filas «es_verifactu_notification_roles» de la empresa (child table
# del lote VeriFactu) y la traducción NOMBRES→EMAILS llega hasta
# Notification Log (enqueue_create_notification matchea por email).
#
# Módulo en tests/ (no carpeta de doctype): sin walk de dependencias ni
# IGNORE (el framework solo lo admite en carpetas de doctype).

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.aeat import utils
from erpnext_spain.aeat.tests.helpers import test_company

NOTIFIER_ROLE = "ES VeriFactu Notificador"
NOTIFIED_USER = "es_notifica_verifactu@test.example.com"


class TestVerifactuCompanyNotifyRoles(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		frappe.get_doc({"doctype": "Role", "role_name": NOTIFIER_ROLE}).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User",
				"email": NOTIFIED_USER,
				"first_name": "ES",
				"last_name": "Notifica VeriFactu",
				"roles": [{"role": NOTIFIER_ROLE}],
				"enabled": 1,
			}
		).insert(ignore_permissions=True)

	def setUp(self):
		frappe.set_user("Administrator")
		# La clase comparte transacción: cada test configura sus propias
		# filas de roles de la empresa.
		frappe.db.delete("ES Verifactu Notification Role", {"parent": self.company})

	def _alerts_for(self, user: str) -> list[dict]:
		return frappe.get_all(
			"Notification Log",
			filters={
				"for_user": user,
				"document_type": "Company",
				"document_name": self.company,
			},
			fields=["subject", "type"],
		)

	def test_roles_configurados_reciben_notification_log(self):
		"""La empresa configura el rol en su tab Spain Compliance; la
		incidencia llega in-app a los usuarios que LO TIENEN (spec 04 §9)."""
		doc = frappe.get_doc("Company", self.company)
		doc.append("es_verifactu_notification_roles", {"role": NOTIFIER_ROLE})
		doc.save(ignore_permissions=True)

		subject = "ES incidencia de prueba"
		utils.notify_roles(self.company, subject, "ES cuerpo de prueba")

		alerts = self._alerts_for(NOTIFIED_USER)
		self.assertTrue(any(a.subject == subject for a in alerts), alerts)
		self.assertTrue(all(a.type == "Alert" for a in alerts), alerts)

	def test_user_names_translated_to_emails(self):
		"""Regresión del fix nombres→emails: los roles devuelven NOMBRES de
		usuario y enqueue_create_notification matchea por EMAIL — un
		destinatario cuyo nombre NO es su email (Administrator) solo recibe
		la notificación si la traducción corre. El emisor es OTRO usuario
		para que la regla de auto-notificación (for_user == from_user) no
		salte a Administrator."""
		email_admin = frappe.db.get_value("User", "Administrator", "email")
		self.assertNotEqual(email_admin, "Administrator")  # nombre ≠ email

		doc = frappe.get_doc("Company", self.company)
		doc.append("es_verifactu_notification_roles", {"role": "System Manager"})
		doc.save(ignore_permissions=True)

		frappe.set_user(NOTIFIED_USER)
		subject = "ES traduccion nombres a emails"
		utils.notify_roles(self.company, subject, "ES cuerpo")

		frappe.set_user("Administrator")  # el listado de avisos consulta como admin
		self.assertTrue(any(a.subject == subject for a in self._alerts_for("Administrator")))
