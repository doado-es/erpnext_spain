# Tests de las utilidades AEAT (spec 13 §7): timestamps Europe/Madrid (caso
# DST incluido), permisos explícitos por empresa+propósito y notificaciones a
# roles por los dos canales (Notification Log + es_incidents_email).

from __future__ import annotations

import os
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.aeat import signer, utils
from erpnext_spain.aeat.tests.helpers import test_company

UTC = ZoneInfo("UTC")
MADRID = ZoneInfo("Europe/Madrid")


class TestAEATFormats(IntegrationTestCase):
	def test_now_aeat_is_madrid_tz_aware(self):
		now = utils.now_aeat()
		self.assertIsNotNone(now.tzinfo)
		self.assertEqual(now.tzinfo.key, "Europe/Madrid")

	def test_format_aeat_datetime_winter_offset_plus_1(self):
		# 30-01-2026: horario de invierno → +01:00
		moment = datetime(2026, 1, 30, 13, 58, 26, tzinfo=UTC)
		self.assertEqual(utils.format_aeat_datetime(moment), "2026-01-30T14:58:26+01:00")

	def test_format_aeat_datetime_summer_offset_plus_2(self):
		# 31-07-2026: horario de verano → +02:00
		moment = datetime(2026, 7, 31, 13, 58, 26, tzinfo=UTC)
		self.assertEqual(utils.format_aeat_datetime(moment), "2026-07-31T15:58:26+02:00")

	def test_format_aeat_datetime_dst_edge_case(self):
		"""Cambio de hora 2026: el último domingo de marzo (29), 01:00 UTC
		son las 02:00 CET (+01:00); a las 01:00:01 UTC ya son las 03:00 CEST
		(+02:00) — el salto no existe en hora local."""
		before = datetime(2026, 3, 29, 0, 59, 0, tzinfo=UTC)
		self.assertEqual(utils.format_aeat_datetime(before), "2026-03-29T01:59:00+01:00")

		after = datetime(2026, 3, 29, 1, 1, 0, tzinfo=UTC)
		self.assertEqual(utils.format_aeat_datetime(after), "2026-03-29T03:01:00+02:00")

	def test_format_aeat_datetime_naive_assumed_madrid(self):
		naive = datetime(2026, 1, 30, 13, 58, 26)
		self.assertEqual(utils.format_aeat_datetime(naive), "2026-01-30T13:58:26+01:00")

	def test_format_aeat_datetime_without_microseconds(self):
		moment = datetime(2026, 1, 30, 13, 58, 26, 123456, tzinfo=MADRID)
		self.assertEqual(utils.format_aeat_datetime(moment), "2026-01-30T13:58:26+01:00")

	def test_format_aeat_date_dd_mm_yyyy(self):
		from datetime import date

		self.assertEqual(utils.format_aeat_date(date(2026, 1, 31)), "31-01-2026")
		self.assertEqual(utils.format_aeat_date(date(2026, 12, 5)), "05-12-2026")
		# un datetime se convierte a fecha MADRID (no la fecha UTC cruda)
		moment = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)  # 01:30 en Madrid
		self.assertEqual(utils.format_aeat_date(moment), "01-01-2026")

	def test_get_days_remaining(self):
		from datetime import date, timedelta

		hoy = utils.now_aeat().date()
		self.assertIsNone(utils.get_days_remaining(None))
		self.assertEqual(utils.get_days_remaining(hoy + timedelta(days=7)), 7)
		self.assertEqual(utils.get_days_remaining(hoy - timedelta(days=3)), -3)
		self.assertEqual(utils.get_days_remaining(str(hoy + timedelta(days=7))), 7)

	def test_signer_passthrough_documentado(self):
		"""Seam de firma (spec 13 §6): passthrough documentado — mismo contenido,
		la autenticación la aporta TLS mutua con la MISMA credencial."""
		payload = {"Cabecera": {"NIF": "12345678Z"}}
		self.assertEqual(signer.sign("Empresa", "VeriFactu", payload), payload)


class TestAbsoluteSitePaths(IntegrationTestCase):
	"""Rutas de site INDEPENDIENTES del CWD (fix del OSError en vivo): los
	workers del planificador corren con CWDs mixtos (raíz del bench y
	sites/) y frappe.get_site_path() devuelve rutas RELATIVAS al CWD — los
	PEM de la TLS mutua y el cerrojo de cadena deben anclarse al bench
	real (get_bench_path, basado en frappe.__file__)."""

	def test_absolute_site_path_anchors_to_bench(self):
		from frappe.utils import get_bench_path

		path = utils.absolute_site_path("private", "files", "x.pem")
		self.assertTrue(os.path.isabs(path), path)
		site_root = os.path.join(get_bench_path(), "sites", frappe.local.site)
		self.assertEqual(path, os.path.join(site_root, "private", "files", "x.pem"))
		self.assertTrue(os.path.isdir(os.path.dirname(path)))

	def test_pem_paths_absolute_under_real_site(self):
		from frappe.utils import get_bench_path

		from erpnext_spain.aeat.doctype.es_aeat_credential.es_aeat_credential import (
			pem_paths,
		)

		cert, key = pem_paths("Mi Empresa SL", "VeriFactu")
		files_root = os.path.join(
			get_bench_path(), "sites", frappe.local.site, "private", "files"
		)
		for path in (cert, key):
			self.assertTrue(os.path.isabs(path), path)
			self.assertTrue(path.startswith(files_root), path)

	def test_chain_lock_absolute(self):
		from erpnext_spain.es_verifactu.utils import locks

		path = locks._lock_path("Mi Empresa SL")
		self.assertTrue(path.is_absolute(), path)
		self.assertIn("locks", str(path))

		lock = locks.acquire_chain_lock("Mi Empresa SL")
		self.addCleanup(locks.release_chain_lock, lock)
		self.assertTrue(os.path.isabs(lock.lock_file), lock.lock_file)
		self.assertTrue(os.path.exists(lock.lock_file), lock.lock_file)


class TestAEATPermissions(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()

		# Credencial habilitada para (company, VeriFactu): los tests de permiso
		# la comparten (el par es único por transacción de la clase).
		from erpnext_spain.aeat.tests.helpers import clean_pem, generate_p12, write_private_p12

		cls.url_p12 = write_private_p12("es_test_permisos.p12", generate_p12()[0])
		frappe.get_doc(
			{
				"doctype": "ES AEAT Credential",
				"company": cls.company,
				"purpose": "VeriFactu",
				"cert_file": cls.url_p12,
				"cert_password": "es-test-pass",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		cls.addClassCleanup(clean_pem, cls.company, "VeriFactu")

		# Usuarios de prueba (rollback de la clase los devuelve a su sitio).
		cls.user = "es_permisos_aeat@test.example.com"
		cls.user_without_role = "es_sin_rol_aeat@test.example.com"
		for email, roles in (
			(cls.user, ["Accounts Manager"]),
			(cls.user_without_role, []),
		):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": "ES",
						"roles": [{"role": role} for role in roles],
						"enabled": 1,
					}
				).insert(ignore_permissions=True)

	def test_administrator_and_system_manager_pass(self):
		self.assertTrue(utils.has_aeat_permission(user="Administrator", company=self.company, purpose="VeriFactu"))
		self.assertTrue(utils.has_aeat_permission(user="Administrator"))

	def test_missing_company_or_purpose_denies(self):
		self.assertFalse(utils.has_aeat_permission(user=self.user))
		self.assertFalse(utils.has_aeat_permission(user=self.user, company=self.company))
		self.assertFalse(utils.has_aeat_permission(user=self.user, purpose="VeriFactu"))

	def test_without_enabled_credential_denies(self):
		"""El permiso es por empresa+propósito: sin credencial habilitada NO
		hay nada que autorizar (doc 12 §18)."""
		self.assertFalse(
			utils.has_aeat_permission(user=self.user, company=self.company, purpose="SII")
		)

	def test_accounts_manager_with_enabled_credential_passes(self):
		self.assertTrue(
			utils.has_aeat_permission(user=self.user, company=self.company, purpose="VeriFactu")
		)

	def test_user_without_relevant_role_denied_with_credential(self):
		"""Un usuario sin System Manager ni Accounts Manager NO dispara
		comunicaciones AEAT aunque exista la credencial."""
		self.assertFalse(
			utils.has_aeat_permission(user=self.user_without_role, company=self.company, purpose="VeriFactu")
		)


class TestNotifyRoles(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.user = "es_notifica_aeat@test.example.com"
		if not frappe.db.exists("User", cls.user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.user,
					"first_name": "ES",
					"last_name": "Notifica AEAT",
					"roles": [{"role": "System Manager"}],
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

	def _notifications_for(self, user: str) -> list[str]:
		return frappe.get_all(
			"Notification Log",
			filters={"for_user": user, "document_type": "Company", "document_name": self.company},
			pluck="subject",
		)

	def test_notify_roles_creates_notification_log_for_role_users(self):
		utils.notify_roles(
			self.company, "ES sujeta", "ES cuerpo", roles=["System Manager"]
		)
		notifications = self._notifications_for(self.user)
		self.assertTrue(any("ES sujeta" in a for a in notifications), notifications)

	def test_notify_roles_roles_none_falls_back_to_system_managers(self):
		"""Sin child table de roles todavía (lote VeriFactu): fallback
		gracioso a System Managers."""
		utils.notify_roles(self.company, "ES fallback", "ES cuerpo")
		notifications = self._notifications_for(self.user)
		self.assertTrue(any("ES fallback" in a for a in notifications), notifications)

	def test_notify_roles_sends_email_to_es_incidents_email(self):
		"""Canal email externo: sendmail al es_incidents_email de la Company
		(mockeado — el envío real depende de la cuenta saliente del site)."""
		frappe.db.set_value("Company", self.company, "es_incidents_email", "asesor@test.example.com")
		self.addCleanup(frappe.db.set_value, "Company", self.company, "es_incidents_email", None)

		with mock.patch("frappe.sendmail") as sendmail:
			utils.notify_roles(self.company, "ES sujeta email", "ES cuerpo")

		sendmail.assert_called_once()
		kwargs = sendmail.call_args.kwargs
		self.assertEqual(kwargs["recipients"], ["asesor@test.example.com"])
		self.assertEqual(kwargs["subject"], "ES sujeta email")

	def test_notify_roles_without_configured_email_does_not_send(self):
		frappe.db.set_value("Company", self.company, "es_incidents_email", None)
		with mock.patch("frappe.sendmail") as sendmail:
			utils.notify_roles(self.company, "ES sin email", "ES cuerpo")
		sendmail.assert_not_called()

	def test_notify_roles_email_failure_does_not_break_notification(self):
		"""Aislamiento de canales: si sendmail revienta (p. ej. site sin
		cuenta saliente), el Notification Log igualmente quedó creado y la
		incidencia se registra en Error Log en lugar de propagar."""
		frappe.db.set_value("Company", self.company, "es_incidents_email", "asesor@test.example.com")
		self.addCleanup(frappe.db.set_value, "Company", self.company, "es_incidents_email", None)

		with mock.patch("frappe.sendmail", side_effect=frappe.OutgoingEmailError("sin cuenta")):
			utils.notify_roles(self.company, "ES email roto", "ES cuerpo")

		notifications = self._notifications_for(self.user)
		self.assertTrue(any("ES email roto" in a for a in notifications), notifications)
		# el fallo del canal email queda registrado, no silenciado
		self.assertTrue(
			frappe.get_all(
				"Error Log",
				filters={"method": f"AEAT: fallo notificando por email de incidencias a {self.company}"},
				pluck="name",
			)
		)
