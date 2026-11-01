# Contraste de NIF y nombre con el censo de la AEAT (es_nif/aeat_census.py).
#
# Cliente simulado (frappe.flags.es_vnif_responses): nunca contra la AEAT real.
# Los comportamientos simulados son los comprobados contra el servicio real el
# 31/10/2026 (ver la cabecera del módulo).

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_nif import aeat_census
from erpnext_spain.es_nif.aeat_census import IDENTIFIED, NAME_MISMATCH, NOT_IDENTIFIED, UNKNOWN

COMPANY_NIF = "B12345674"
PERSON_NIF = "12345678Z"


class TestNames(IntegrationTestCase):
	def test_normalize_name(self):
		self.assertEqual(aeat_census.normalize_name("Empresa  Ejemplo, S.L."), "EMPRESA EJEMPLO SL")
		self.assertEqual(aeat_census.normalize_name("Vázquez Cabo   Alberto "), "VAZQUEZ CABO ALBERTO")
		self.assertEqual(aeat_census.normalize_name(None), "")

	def test_status_from(self):
		self.assertEqual(aeat_census.status_from("IDENTIFICADO", "EMPRESA SL", "EMPRESA, S.L."), IDENTIFIED)
		self.assertEqual(aeat_census.status_from("IDENTIFICADO", "EMPRESA SLU", "EMPRESA, SL"), NAME_MISMATCH)
		self.assertEqual(aeat_census.status_from("NO IDENTIFICADO", "X", "X"), NOT_IDENTIFIED)
		self.assertEqual(aeat_census.status_from("OTRA COSA", "X", "X"), UNKNOWN)

	def test_clean_and_spanish_nif(self):
		self.assertEqual(aeat_census.clean_nif("es-b12345674"), COMPANY_NIF)
		self.assertTrue(aeat_census.is_spanish_nif("12345678-Z"))
		self.assertFalse(aeat_census.is_spanish_nif("FR40303265045"))


class TestCheckTaxId(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.es_vnif_responses = {
			PERSON_NIF: ("IDENTIFICADO", "EJEMPLO PRUEBA ALBERTO          "),
			COMPANY_NIF: ("IDENTIFICADO", "EMPRESA DE CENSO, SL"),
		}
		self.addCleanup(setattr, frappe.flags, "es_vnif_responses", None)
		patcher = mock.patch("erpnext_spain.es_aeat.utils.require_credential", return_value="x")
		patcher.start()
		self.addCleanup(patcher.stop)

	def check(self, tax_id: str, name: str) -> dict:
		return aeat_census.check_tax_id("Customer", tax_id, name, company="_Test ES Company")

	def test_results(self):
		"""Persona física en otro orden: identificada, pero con el nombre del censo
		(«APELLIDO APELLIDO NOMBRE»), que es el que exige VeriFactu."""
		self.assertEqual(
			self.check(PERSON_NIF, "Alberto Ejemplo Prueba"),
			{"status": NAME_MISMATCH, "result": "IDENTIFICADO", "census_name": "EJEMPLO PRUEBA ALBERTO"},
		)
		self.assertEqual(self.check(PERSON_NIF, "EJEMPLO PRUEBA ALBERTO")["status"], IDENTIFIED)
		self.assertEqual(self.check("ES-" + COMPANY_NIF, "Empresa de Censo S.L.")["status"], IDENTIFIED)
		self.assertEqual(self.check("87654321X", "Nadie")["status"], NOT_IDENTIFIED)

	def test_nothing_is_stored(self):
		for doctype in aeat_census.PARTY_DOCTYPES:
			fields = [field.fieldname for field in frappe.get_meta(doctype).fields]
			self.assertFalse([f for f in fields if f.startswith("es_aeat_")], doctype)

	def test_foreign_nif_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.check("FR40303265045", "Société Exemple")

	def test_requires_role(self):
		user = "es_census_sin_rol@test.example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "ES"}).insert()
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			self.check(COMPANY_NIF, "X")
