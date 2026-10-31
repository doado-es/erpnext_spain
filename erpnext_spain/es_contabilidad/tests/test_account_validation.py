# Validación de cuentas nuevas en compañías PGC (spec 02 §4).

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.account import expected_root_type
from erpnext_spain.es_contabilidad.tests.test_apply_pgc import make_company


def account_by_number(company: str, number: str) -> str:
	return frappe.get_value("Account", {"company": company, "account_number": number}, "name")


class TestAccountRootRules(IntegrationTestCase):
	def test_longest_prefix_wins(self):
		self.assertEqual(expected_root_type("5721"), "Asset")
		self.assertEqual(expected_root_type("4000001"), "Liability")
		self.assertEqual(expected_root_type("4070001"), "Asset")
		self.assertEqual(expected_root_type("10340"), "Liability")
		self.assertEqual(expected_root_type("6290001"), "Expense")


class TestAccountValidation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = make_company("_Test ES Cuentas", "_TECU")
		if not frappe.get_cached_value("Company", cls.company, "es_pgc_applied"):
			pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		cls.foreign = make_company("_Test ES Cuentas Alemania", "_TECA", country="Germany")

	def new_account(
		self, name: str, parent: str, number: str | None = None, company: str | None = None, **kw
	):
		return frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": name,
				"account_number": number,
				"parent_account": parent,
				"company": company or self.company,
				**kw,
			}
		)

	def test_leaf_with_coherent_number_is_accepted(self):
		parent = account_by_number(self.company, "572")
		account = self.new_account("Banco segundo", parent, "5721").insert()
		self.assertEqual(account.root_type, "Asset")

	def test_leaf_without_number_rejected(self):
		parent = account_by_number(self.company, "572")
		with self.assertRaisesRegex(frappe.ValidationError, "no tiene número"):
			self.new_account("Banco sin número", parent).insert()

	def test_group_without_number_allowed(self):
		parent = account_by_number(self.company, "572")
		self.new_account("Bancos extranjeros", parent, is_group=1).insert()

	def test_number_outside_parent_prefix_rejected(self):
		parent = account_by_number(self.company, "572")
		with self.assertRaisesRegex(frappe.ValidationError, "debe empezar por <strong>572</strong>"):
			self.new_account("Banco mal numerado", parent, "6290001").insert()

	def test_wrong_branch_rejected(self):
		# 407 (anticipos a proveedores) va en Activo aunque el subgrupo 40 esté en Pasivo:
		# colgar una 407x de una cuenta numerada de Pasivo sin número común no es posible,
		# así que se prueba colgando del grupo sin número de la raíz de Pasivo.
		liability_root = frappe.get_value(
			"Account",
			{
				"company": self.company,
				"is_group": 1,
				"parent_account": ["in", ["", None]],
				"root_type": "Liability",
			},
			"name",
		)
		with self.assertRaisesRegex(frappe.ValidationError, "rama"):
			self.new_account("Anticipo mal colocado", liability_root, "4071").insert()

	def test_renumbering_checked(self):
		parent = account_by_number(self.company, "572")
		account = self.new_account("Banco tercero", parent, "5722").insert()
		account.account_number = "6000001"
		with self.assertRaises(frappe.ValidationError):
			account.save()

	def test_non_pgc_company_untouched(self):
		parent = frappe.get_value(
			"Account",
			{"company": self.foreign, "is_group": 1, "root_type": "Asset"},
			"name",
			order_by="lft desc",
		)
		self.new_account("Cuenta sin número", parent, company=self.foreign).insert()
