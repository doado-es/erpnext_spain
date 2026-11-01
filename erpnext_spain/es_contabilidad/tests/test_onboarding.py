# Tests del plan PGC automático: etapa del asistente y compañías nuevas (onboarding.py).

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_contabilidad import onboarding
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company


def new_company(name: str, abbr: str, country: str = "Spain", **extra) -> frappe._dict:
	"""Compañía sin insertar (para comprobar after_insert)."""
	return frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": name,
			"abbr": abbr,
			"country": country,
			"default_currency": "EUR",
			"chart_of_accounts": "Standard",
			**extra,
		}
	)


def notices(mock_publish) -> list[dict]:
	return [c.args[1] for c in mock_publish.call_args_list if c.args[0] == onboarding.NOTICE_EVENT]


class TestSetupWizardStage(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_stage_is_registered_after_erpnext_company_stage(self):
		from frappe.desk.page.setup_wizard.setup_wizard import get_stages_hooks

		tasks = [task["fn"] for stage in get_stages_hooks({}) for task in stage["tasks"]]
		names = [f"{fn.__module__}.{fn.__name__}" for fn in tasks]
		ours = names.index("erpnext_spain.es_contabilidad.onboarding.apply_from_setup_wizard")
		self.assertGreater(ours, names.index("erpnext.setup.setup_wizard.setup_wizard.setup_company"))
		self.assertGreater(ours, names.index("erpnext.setup.setup_wizard.setup_wizard.setup_defaults"))

	def test_applies_chosen_model(self):
		company = make_company("_Test ES Asistente Normal", "_TEAN")
		onboarding.apply_from_setup_wizard(
			{"country": "Spain", "company_name": company, "es_chart_model": "Normal"}
		)
		values = frappe.db.get_value("Company", company, ["es_pgc_applied", "es_chart_model"], as_dict=True)
		self.assertEqual(values.es_pgc_applied, 1)
		self.assertEqual(values.es_chart_model, "Normal")

	def test_defaults_to_pymes(self):
		company = make_company("_Test ES Asistente PYMES", "_TEAP")
		onboarding.apply_from_setup_wizard({"country": "Spain", "company_name": company})
		self.assertEqual(frappe.db.get_value("Company", company, "es_chart_model"), "PYMES")

	def test_skips_other_countries(self):
		company = make_company("_Test ES Asistente Alemania", "_TEAA", country="Germany")
		onboarding.apply_from_setup_wizard({"country": "Germany", "company_name": company})
		self.assertFalse(frappe.db.get_value("Company", company, "es_pgc_applied"))

	def test_skips_company_that_already_has_pgc(self):
		company = make_company("_Test ES Asistente Repetido", "_TEAR")
		args = {"country": "Spain", "company_name": company}
		onboarding.apply_from_setup_wizard(args)
		# Una segunda ejecución (reintento del asistente) no falla.
		onboarding.apply_from_setup_wizard(args)
		self.assertEqual(frappe.db.get_value("Company", company, "es_pgc_applied"), 1)


class TestAutoApplyOnInsert(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.es_auto_apply_pgc_in_test = True
		self.addCleanup(setattr, frappe.flags, "es_auto_apply_pgc_in_test", False)
		frappe.clear_messages()

	def test_enqueues_after_commit_with_annual_accounts_model(self):
		with patch.object(frappe, "enqueue") as enqueue:
			doc = new_company("_Test ES Auto Normal", "_TEAUN", es_annual_accounts_model="Normal").insert()
		enqueue.assert_called_once()
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(
			enqueue.call_args.args[0], "erpnext_spain.es_contabilidad.onboarding.apply_in_background"
		)
		self.assertTrue(kwargs["enqueue_after_commit"])
		self.assertEqual(kwargs["company"], doc.name)
		self.assertEqual(kwargs["chart_model"], "Normal")

	def test_abbreviated_accounts_use_pymes(self):
		with patch.object(frappe, "enqueue") as enqueue:
			new_company("_Test ES Auto Abreviado", "_TEAUA", es_annual_accounts_model="Abreviado").insert()
		self.assertEqual(enqueue.call_args.kwargs["chart_model"], "PYMES")

	def test_other_countries_are_ignored(self):
		with patch.object(frappe, "enqueue") as enqueue:
			new_company("_Test ES Auto Alemania", "_TEAUG", country="Germany").insert()
		enqueue.assert_not_called()

	def test_setup_wizard_uses_its_own_stage(self):
		frappe.flags.in_setup_wizard = True
		self.addCleanup(setattr, frappe.flags, "in_setup_wizard", False)
		with patch.object(frappe, "enqueue") as enqueue:
			new_company("_Test ES Auto Asistente", "_TEAUW").insert()
		enqueue.assert_not_called()

	def test_unmet_precondition_only_warns(self):
		with patch.object(frappe, "enqueue") as enqueue:
			new_company("_Test ES Auto Abreviatura", "_TEAU_ABBR_13").insert()
		enqueue.assert_not_called()
		messages = " ".join(m.get("message", "") for m in map(frappe.parse_json, frappe.get_message_log()))
		self.assertIn("No se ha aplicado el plan PGC automáticamente", messages)
		self.assertIn("abreviatura", messages)

	def test_disabled_in_tests_without_flag(self):
		frappe.flags.es_auto_apply_pgc_in_test = False
		with patch.object(frappe, "enqueue") as enqueue:
			new_company("_Test ES Auto Sin Bandera", "_TEAUF").insert()
		enqueue.assert_not_called()


class TestApplyInBackground(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_applies_and_notifies(self):
		company = make_company("_Test ES Fondo PYMES", "_TEFP")
		with patch.object(frappe, "publish_realtime") as publish:
			onboarding.apply_in_background(company, "PYMES")
		self.assertEqual(frappe.db.get_value("Company", company, "es_pgc_applied"), 1)
		self.assertEqual([n["indicator"] for n in notices(publish)], ["green"])

	def test_failure_notifies_and_raises(self):
		company = make_company("_Test ES Fondo Alemania", "_TEFA", country="Germany")
		with patch.object(frappe, "publish_realtime") as publish, self.assertRaises(frappe.ValidationError):
			onboarding.apply_in_background(company, "PYMES")
		self.assertEqual([n["indicator"] for n in notices(publish)], ["red"])
