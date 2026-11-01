# Completar clientes y proveedores con los datos de VIES.

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from erpnext_spain.es_nif import vies

RESPONSE = {
	"valid": True,
	"name": "SA ODIGEO",
	"address": "1 RUE DE LA PAIX\nBATIMENT B\n75002 PARIS",
	"request_identifier": "WAPIAAAAZ123",
}


class TestParseAddress(UnitTestCase):
	def test_postcode_and_city_on_last_line(self):
		parsed = vies.parse_address("1 RUE DE LA PAIX\nBATIMENT B\n75002 PARIS", "FR")
		self.assertEqual(
			{k: parsed[k] for k in ("address_line1", "address_line2", "pincode", "city")},
			{
				"address_line1": "1 RUE DE LA PAIX",
				"address_line2": "BATIMENT B",
				"pincode": "75002",
				"city": "PARIS",
			},
		)

	def test_dutch_and_prefixed_postcodes(self):
		self.assertEqual(vies.parse_address("DAM 1\n1012 AB AMSTERDAM", "NL")["pincode"], "1012 AB")
		self.assertEqual(vies.parse_address("RUE X 2\nL-1234 LUXEMBOURG", "LU")["city"], "LUXEMBOURG")

	def test_greece_and_empty(self):
		self.assertIsNone(vies.parse_address("", "DE"))
		self.assertEqual(vies.provided("---"), "")


class TestViesDetails(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.es_vies_responses = {"FR40303265045": RESPONSE, "DE123456789": {"valid": False}}
		self.addCleanup(setattr, frappe.flags, "es_vies_responses", None)

	def customer(self, name: str, tax_id: str) -> str:
		if not frappe.db.exists("Customer", name):
			frappe.get_doc({"doctype": "Customer", "customer_name": name, "tax_id": tax_id}).insert()
		return name

	def test_details_and_apply(self):
		name = self.customer("_Test ES VIES completar", "FR40303265045")
		details = vies.vies_details("Customer", name)
		self.assertEqual(details["status"], vies.VALID)
		self.assertEqual(details["request_identifier"], "WAPIAAAAZ123")
		self.assertEqual(details["parsed_address"]["country"], "France")
		self.assertEqual(frappe.db.get_value("Customer", name, "es_vies_address"), RESPONSE["address"])

		result = vies.apply_vies_details("Customer", name, update_name=1, create_address=1)
		self.assertEqual(frappe.db.get_value("Customer", name, "customer_name"), "SA ODIGEO")
		address = frappe.get_doc("Address", result["address"])
		self.assertEqual((address.city, address.pincode, address.is_primary_address), ("PARIS", "75002", 1))
		# Una segunda vez no duplica la dirección.
		self.assertEqual(vies.apply_vies_details("Customer", name, create_address=1)["address"], address.name)

	def test_apply_requires_valid_check(self):
		name = self.customer("_Test ES VIES no válido detalle", "DE123456789")
		self.assertEqual(vies.vies_details("Customer", name)["status"], vies.INVALID)
		self.assertRaises(frappe.ValidationError, vies.apply_vies_details, "Customer", name, 1, 1)

	def test_only_parties(self):
		self.assertRaises(frappe.ValidationError, vies.vies_details, "Item", "x")
