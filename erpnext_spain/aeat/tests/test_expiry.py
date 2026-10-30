# Tests del aviso diario de caducidad de certificados (spec 13 §2 + spec 04
# §15): a 30/7/1 días (y el día de caducidad) por los DOS canales.

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.aeat.tasks import notify_certificate_expiry
from erpnext_spain.aeat.utils import now_aeat
from erpnext_spain.aeat.tests.helpers import (
	test_company,
	write_private_p12,
	generate_p12,
	clean_pem,
)


class TestCertificateExpiryWarnings(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.url_p12 = write_private_p12("es_test_caducidad.p12", generate_p12(days_to=100)[0])
		cls.addClassCleanup(clean_pem, cls.company, "VeriFactu")
		cls.addClassCleanup(clean_pem, cls.company, "SII")

	def setUp(self):
		super().setUp()
		# Los tests de la clase comparten transacción: cada test arranca con
		# las credenciales habilitadas y FUERA de la ventana de aviso (30/7/1/0
		# días) — cada test fija la marca exacta que ejercita. Sin esto, la
		# credencial de un test anterior (p. ej. SII a 30 de
		# test_notifies_thirty_days_before_expiry) sigue dentro de la ventana
		# y dispara notificaciones cruzadas.
		for name in frappe.get_all(
			"ES AEAT Credential", filters={"company": self.company}, pluck="name"
		):
			frappe.db.set_value("ES AEAT Credential", name, "enabled", 1)
			frappe.db.set_value(
				"ES AEAT Credential",
				name,
				"valid_until",
				now_aeat().date() + timedelta(days=15),
			)

	@classmethod
	def _credential(cls, purpose: str) -> str:
		"""Credencial del par (idempotente dentro de la transacción de la clase)."""
		name = frappe.db.exists("ES AEAT Credential", {"company": cls.company, "purpose": purpose})
		if not name:
			doc = frappe.get_doc(
				{
					"doctype": "ES AEAT Credential",
					"company": cls.company,
					"purpose": purpose,
					"cert_file": cls.url_p12,
					"cert_password": "es-test-pass",
					"enabled": 1,
				}
			)
			doc.insert(ignore_permissions=True)
			name = doc.name
		return name

	@staticmethod
	def _set_validity(name: str, days: int) -> None:
		"""Fija valid_until exacto (el validate lo parsea del p12; aquí
		queremos la marca exacta 30/7/1/0 para el scheduler)."""
		frappe.db.set_value(
			"ES AEAT Credential", name, "valid_until", now_aeat().date() + timedelta(days=days)
		)

	def _in_app_notifications(self) -> list[str]:
		return frappe.get_all(
			"Notification Log",
			filters={"for_user": "Administrator", "document_type": "Company", "document_name": self.company},
			pluck="subject",
		)

	def test_notifies_seven_days_before_expiry_both_channels(self):
		name = self._credential("VeriFactu")
		self._set_validity(name, 7)

		frappe.db.set_value("Company", self.company, "es_incidents_email", "asesor@test.example.com")
		self.addCleanup(frappe.db.set_value, "Company", self.company, "es_incidents_email", None)

		with mock.patch("frappe.sendmail") as sendmail:
			notified = notify_certificate_expiry()

		# trazabilidad del job (filtrada por la credencial del test)
		marks = {n["credential"]: n["days"] for n in notified}
		self.assertEqual(marks.get(name), 7)
		# canal in-app: Notification Log con mensaje y remedio
		notifications = self._in_app_notifications()
		notification = next(a for a in notifications if "caduca en 7 días" in a and "(VeriFactu)" in a)
		self.assertIn(self.company, notification)
		# canal email: sendmail al email de incidencias de la Company
		sendmail.assert_called_once()
		kwargs = sendmail.call_args.kwargs
		self.assertEqual(kwargs["recipients"], ["asesor@test.example.com"])
		self.assertIn("caduca en 7 días", kwargs["subject"])
		self.assertIn("Remedio", kwargs["message"])

	def test_notifies_thirty_days_before_expiry(self):
		name_30 = self._credential("SII")
		self._set_validity(name_30, 30)

		notified = notify_certificate_expiry()
		marks = {n["credential"]: n["days"] for n in notified}
		self.assertEqual(marks.get(name_30), 30)

	def test_notifies_on_expiry_day(self):
		name = self._credential("SII")
		self._set_validity(name, 0)

		notified = notify_certificate_expiry()
		marks = {n["credential"]: n["days"] for n in notified}
		self.assertEqual(marks.get(name), 0)
		notifications = self._in_app_notifications()
		self.assertTrue(any("CADUCA HOY" in a for a in notifications), notifications)

	def test_no_notification_outside_window(self):
		name = self._credential("SII")
		self._set_validity(name, 15)

		notified = notify_certificate_expiry()
		self.assertFalse(any(n["credential"] == name for n in notified))

	def test_disabled_credential_not_notified(self):
		name = self._credential("SII")
		self._set_validity(name, 7)
		frappe.db.set_value("ES AEAT Credential", name, "enabled", 0)

		notified = notify_certificate_expiry()
		self.assertFalse(any(n["credential"] == name for n in notified))

	def test_repeats_daily_within_window(self):
		"""La repetición diaria es intencionada (recordatorio): dos corridas
		del job ambas notifican."""
		name = self._credential("SII")
		self._set_validity(name, 7)

		with mock.patch("frappe.sendmail"):
			notify_certificate_expiry()
			notify_certificate_expiry()

		notifications = self._in_app_notifications()
		self.assertEqual(
			sum(1 for a in notifications if "caduca en 7 días" in a and "(SII)" in a), 2
		)
