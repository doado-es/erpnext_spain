# Tests de la activación por compañía (spec 01 §5) y de los campos del módulo
# base. Crean sus propias compañías: no dependen de los datos del sitio (H8).

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.erpnext_spain.setup import COMPANY_FIELDS
from erpnext_spain.utils.gating import is_feature_enabled, is_pgc_company


def make_company(name: str, abbr: str, country: str, currency: str) -> str:
	if not frappe.db.exists("Company", name):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": name,
				"abbr": abbr,
				"country": country,
				"default_currency": currency,
				"chart_of_accounts": "Standard",
			}
		).insert()
	return name


class TestGating(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.spanish = make_company("_Test ES Gating España", "_TEGE", "Spain", "EUR")
		cls.foreign = make_company("_Test ES Gating Alemania", "_TEGA", "Germany", "EUR")

	def setUp(self):
		for company in (self.spanish, self.foreign):
			frappe.db.set_value("Company", company, {"es_pgc_applied": 0, "es_fiscal_numbering": 0})

	def test_unknown_or_empty_company_is_not_pgc(self):
		self.assertFalse(is_pgc_company(None))
		self.assertFalse(is_pgc_company(""))
		self.assertFalse(is_pgc_company("_Test ES Compañía Inexistente"))

	def test_spanish_company_without_pgc_is_not_pgc(self):
		self.assertFalse(is_pgc_company(self.spanish))

	def test_spanish_company_with_pgc_is_pgc(self):
		frappe.db.set_value("Company", self.spanish, "es_pgc_applied", 1)
		self.assertTrue(is_pgc_company(self.spanish))

	def test_foreign_company_with_flag_is_not_pgc(self):
		"""La marca sola no basta: la compañía tiene que ser de España (R7)."""
		frappe.db.set_value("Company", self.foreign, "es_pgc_applied", 1)
		self.assertFalse(is_pgc_company(self.foreign))

	def test_cache_follows_changes(self):
		"""get_cached_value se invalida al cambiar la compañía: activar y
		desactivar se ve en la siguiente llamada."""
		self.assertFalse(is_pgc_company(self.spanish))
		frappe.db.set_value("Company", self.spanish, "es_pgc_applied", 1)
		self.assertTrue(is_pgc_company(self.spanish))
		frappe.db.set_value("Company", self.spanish, "es_pgc_applied", 0)
		self.assertFalse(is_pgc_company(self.spanish))

	def test_feature_flag_per_company(self):
		frappe.db.set_value("Company", self.spanish, "es_fiscal_numbering", 1)
		self.assertTrue(is_feature_enabled(self.spanish, "es_fiscal_numbering"))
		self.assertFalse(is_feature_enabled(self.foreign, "es_fiscal_numbering"))

	def test_feature_flag_unknown_company_or_missing_field(self):
		self.assertFalse(is_feature_enabled(None, "es_fiscal_numbering"))
		self.assertFalse(is_feature_enabled("_Test ES Compañía Inexistente", "es_fiscal_numbering"))
		self.assertFalse(is_feature_enabled(self.spanish, "es_campo_que_no_existe"))

	def test_feature_flag_rejects_non_app_fields(self):
		with self.assertRaises(ValueError):
			is_feature_enabled(self.spanish, "is_group")


class TestBaseModuleFields(IntegrationTestCase):
	def test_company_fields_exist_in_spain_tab(self):
		meta = frappe.get_meta("Company")
		fieldnames = [df.fieldname for df in meta.fields]
		tab = fieldnames.index("es_tab")
		verifactu = fieldnames.index("es_seccion_verifactu")
		for field in COMPANY_FIELDS:
			position = fieldnames.index(field["fieldname"])
			self.assertTrue(
				tab < position < verifactu,
				f"{field['fieldname']} debe estar en la pestaña de la app, antes de VeriFactu",
			)

	def test_pgc_fields_are_read_only(self):
		meta = frappe.get_meta("Company")
		for fieldname in ("es_pgc_applied", "es_chart_model", "es_initial_data_version"):
			self.assertTrue(meta.get_field(fieldname).read_only, fieldname)

	def test_after_migrate_is_idempotent(self):
		from erpnext_spain.install import setup_custom_fields

		before = frappe.get_all("Custom Field", filters={"dt": "Company", "fieldname": ["like", "es\\_%"]})
		setup_custom_fields()
		after = frappe.get_all("Custom Field", filters={"dt": "Company", "fieldname": ["like", "es\\_%"]})
		self.assertEqual(len(before), len(after))
