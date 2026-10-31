# Contraste de NIF y nombre con el censo de la AEAT (nif/aeat_census.py).
#
# Cliente simulado (frappe.flags.es_vnif_responses): nunca contra la AEAT real.
# Los comportamientos simulados son los comprobados contra el servicio real el
# 31/10/2026 (ver la cabecera del módulo).

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.nif import aeat_census
from erpnext_spain.nif.aeat_census import IDENTIFIED, NAME_MISMATCH, NOT_IDENTIFIED, UNKNOWN

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


class TestCensusCheck(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.es_vnif_responses = {}
		self.addCleanup(setattr, frappe.flags, "es_vnif_responses", None)

	def customer(self, name: str, tax_id: str) -> str:
		return frappe.get_doc({"doctype": "Customer", "customer_name": name, "tax_id": tax_id}).insert().name

	def state(self, name: str, doctype: str = "Customer") -> dict:
		return frappe.db.get_value(doctype, name, list(aeat_census.STATE_FIELDS), as_dict=True)

	def test_identified_mismatch_and_not_identified(self):
		"""Persona física en otro orden: el censo la identifica pero con su nombre
		(«APELLIDO APELLIDO NOMBRE»), que es el que exige VeriFactu."""
		person = self.customer("Alberto Ejemplo Prueba", PERSON_NIF)
		company = self.customer("Empresa de Censo SL", COMPANY_NIF)
		foreign = self.customer("Société Exemple", "FR40303265045")
		frappe.flags.es_vnif_responses = {
			PERSON_NIF: ("IDENTIFICADO", "EJEMPLO PRUEBA ALBERTO          "),
			COMPANY_NIF: ("IDENTIFICADO", "EMPRESA DE CENSO, SL"),
		}
		summary = aeat_census.check_parties_now("Customer", [person, company, foreign], "_Test ES Company")

		self.assertEqual(summary[person], NAME_MISMATCH)
		self.assertEqual(self.state(person).es_aeat_census_name, "EJEMPLO PRUEBA ALBERTO")
		self.assertEqual(summary[company], IDENTIFIED)
		self.assertIsNone(self.state(company).es_aeat_census_name)
		self.assertEqual(self.state(company).es_aeat_source, aeat_census.SOURCE_SERVICE)
		self.assertNotIn(summary[foreign], aeat_census.STATUSES)
		self.assertFalse(self.state(foreign).es_aeat_status)

		frappe.flags.es_vnif_responses = {}
		aeat_census.check_parties_now("Customer", [company], "_Test ES Company")
		self.assertEqual(self.state(company).es_aeat_status, NOT_IDENTIFIED)

	def test_census_name_applied_then_change_resets(self):
		person = self.customer("Alberto Ejemplo Prueba", PERSON_NIF)
		frappe.flags.es_vnif_responses = {PERSON_NIF: ("IDENTIFICADO", "EJEMPLO PRUEBA ALBERTO")}
		aeat_census.check_parties_now("Customer", [person], "_Test ES Company")

		doc = frappe.get_doc("Customer", person)
		doc.customer_name = "EJEMPLO PRUEBA ALBERTO"  # «Usar el nombre del censo»
		doc.save()
		self.assertEqual(doc.es_aeat_status, IDENTIFIED)
		self.assertIsNone(doc.es_aeat_census_name)

		doc.tax_id = "87654321X"
		doc.save()
		self.assertFalse(doc.es_aeat_status)
		self.assertIsNone(doc.es_aeat_checked_on)

	def test_accepted_submission_marks_identified(self):
		company = self.customer("Empresa Aceptada SL", COMPANY_NIF)
		aeat_census.mark_from_submission(
			"Customer", company, "ES" + COMPANY_NIF, "EMPRESA ACEPTADA, S.L.", aeat_census.SOURCE_VERIFACTU
		)
		state = self.state(company)
		self.assertEqual((state.es_aeat_status, state.es_aeat_source), (IDENTIFIED, "VeriFactu"))

		other = self.customer("Empresa Renombrada SL", COMPANY_NIF)
		aeat_census.mark_from_submission("Customer", other, COMPANY_NIF, "OTRO NOMBRE SL", "SII")
		aeat_census.mark_from_submission("Customer", "No existe", COMPANY_NIF, "X", "SII")  # no lanza
		self.assertFalse(self.state(other).es_aeat_status)

	def test_endpoint_requires_role(self):
		user = "es_census_sin_rol@test.example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "ES"}).insert()
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			aeat_census.check_parties("Customer", ["x"])

	def test_fields_on_both_parties(self):
		for doctype in aeat_census.PARTY_DOCTYPES:
			field = frappe.get_meta(doctype).get_field(aeat_census.STATUS)
			self.assertIsNotNone(field, doctype)
			self.assertTrue(field.in_list_view)


class TestCensusOnSave(IntegrationTestCase):
	"""Contraste al guardar (doc_event on_change) si cambian el NIF o el nombre."""

	def setUp(self):
		from unittest import mock

		frappe.set_user("Administrator")
		frappe.flags.es_vnif_responses = {COMPANY_NIF: ("IDENTIFICADO", "EMPRESA AL GUARDAR, SL")}
		self.addCleanup(setattr, frappe.flags, "es_vnif_responses", None)
		patcher = mock.patch.object(aeat_census, "census_company", return_value="_Test ES Company")
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_checked_on_insert_and_on_change(self):
		doc = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "Empresa al guardar SL", "tax_id": COMPANY_NIF}
		).insert()
		# en el documento (lo que recibe el formulario) y en la base de datos
		self.assertEqual(doc.es_aeat_status, IDENTIFIED)
		self.assertEqual(frappe.db.get_value("Customer", doc.name, "es_aeat_status"), IDENTIFIED)

		doc.customer_name = "Empresa con otro nombre SL"
		doc.save()
		self.assertEqual(doc.es_aeat_status, NAME_MISMATCH)
		self.assertEqual(doc.es_aeat_census_name, "EMPRESA AL GUARDAR, SL")

		doc.website = "https://example.com"  # sin cambiar NIF ni nombre: no se consulta
		frappe.flags.es_vnif_responses = {}
		doc.save()
		self.assertEqual(doc.es_aeat_status, NAME_MISMATCH)

	def test_service_failure_does_not_block_save(self):
		from unittest import mock

		with mock.patch.object(aeat_census.SimulatedVNifClient, "check", side_effect=ConnectionError("AEAT")):
			doc = frappe.get_doc(
				{"doctype": "Customer", "customer_name": "Empresa sin red SL", "tax_id": COMPANY_NIF}
			).insert()
		self.assertTrue(frappe.db.exists("Customer", doc.name))
		self.assertFalse(doc.es_aeat_status)

	def test_tests_never_call_the_real_service(self):
		frappe.flags.es_vnif_responses = None
		doc = frappe.get_doc(
			{"doctype": "Customer", "customer_name": "Empresa sin simular SL", "tax_id": COMPANY_NIF}
		).insert()
		self.assertFalse(doc.es_aeat_status)
