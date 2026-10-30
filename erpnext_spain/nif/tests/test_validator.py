# Vectores de validación pura (spec 14 §5). Sin site: UnitTestCase.

from __future__ import annotations

from frappe.tests import UnitTestCase
from stdnum.es import cif as stdnum_cif

from erpnext_spain.nif import validator


class TestNifValidator(UnitTestCase):
	def test_valid_dni(self):
		result = validator.validate_spanish_tax_id("12345678Z")
		self.assertEqual(result.kind, "dni")
		self.assertEqual(result.number, "12345678Z")

	def test_dni_normalizes_spaces_hyphens_prefix(self):
		result = validator.validate_spanish_tax_id(" 12345678-Z ")
		self.assertEqual(result.number, "12345678Z")
		result = validator.validate_spanish_tax_id("ES B64717838")
		self.assertEqual((result.kind, result.number), ("cif", "B64717838"))

	def test_wrong_dni_control_letter_suggests_correct_one(self):
		with self.assertRaises(validator.InvalidTaxID) as ctx:
			validator.validate_spanish_tax_id("12345678A")
		self.assertEqual(ctx.exception.error_type, validator.CONTROL_LETTER)
		self.assertEqual(ctx.exception.suggestion, "Z")
		self.assertIn("¿quisiste decir `Z`?", str(ctx.exception))

	def test_nie_xyz_variants(self):
		for number in ("X2482300W", "Y2482300Q", "Z2482300F"):
			result = validator.validate_spanish_tax_id(number)
			self.assertEqual(result.kind, "nie")
			self.assertEqual(result.number, number)

	def test_wrong_nie_letter_suggests_correct_one(self):
		with self.assertRaises(validator.InvalidTaxID) as ctx:
			validator.validate_spanish_tax_id("X2482300A")
		self.assertEqual(ctx.exception.error_type, validator.CONTROL_LETTER)
		self.assertEqual(ctx.exception.suggestion, "W")

	def test_valid_cif_control_digit(self):
		result = validator.validate_spanish_tax_id("B64717838")
		self.assertEqual(result.kind, "cif")
		self.assertEqual(result.number, "B64717838")

	def test_valid_cif_control_letter_and_jabcdefghi_table(self):
		control_digits = stdnum_cif.calc_check_digits("J9921658")
		digit, letter = control_digits[0], control_digits[1]
		self.assertEqual(letter, "JABCDEFGHI"[int(digit)])
		result = validator.validate_spanish_tax_id("J9921658" + letter)
		self.assertEqual((result.kind, result.number), ("cif", "J9921658B"))

	def test_wrong_cif_control_digit_suggests(self):
		with self.assertRaises(validator.InvalidTaxID) as ctx:
			validator.validate_spanish_tax_id("J99216583")
		self.assertEqual(ctx.exception.error_type, validator.CONTROL_DIGIT)
		self.assertEqual(ctx.exception.suggestion, "2")
		self.assertIn("`B`", str(ctx.exception))

	def test_wrong_cif_control_letter_suggests(self):
		with self.assertRaises(validator.InvalidTaxID) as ctx:
			validator.validate_spanish_tax_id("B6471783B")
		self.assertEqual(ctx.exception.error_type, validator.CONTROL_LETTER)
		self.assertEqual(ctx.exception.suggestion, "H")
		self.assertIn("`8`", str(ctx.exception))

	def test_invalid_cif_org_letter(self):
		with self.assertRaises(validator.InvalidTaxID) as ctx:
			validator.validate_spanish_tax_id("T85810679")
		self.assertEqual(ctx.exception.error_type, validator.ORG_LETTER)
		self.assertIn("letras válidas", str(ctx.exception))

	def test_historic_personal_klm_nif(self):
		result = validator.validate_spanish_tax_id("M1234567L")
		self.assertEqual((result.kind, result.number), ("dni", "M1234567L"))

	def test_wrong_klm_letter_suggests(self):
		with self.assertRaises(validator.InvalidTaxID) as ctx:
			validator.validate_spanish_tax_id("M1234567A")
		self.assertEqual(ctx.exception.error_type, validator.CONTROL_LETTER)
		self.assertEqual(ctx.exception.suggestion, "L")

	def test_unrecognized_format(self):
		for garbage in ("85810678", "FR12345678", "1234567890A", "ABCDEFGHW"):
			with self.assertRaises(validator.InvalidTaxID) as ctx:
				validator.validate_spanish_tax_id(garbage)
			self.assertEqual(ctx.exception.error_type, validator.FORMAT)

	def test_empty(self):
		with self.assertRaises(validator.InvalidTaxID) as ctx:
			validator.validate_spanish_tax_id("")
		self.assertEqual(ctx.exception.error_type, validator.FORMAT)

	def test_looks_spanish(self):
		spanish_cases = ("12345678Z", "X2482300W", "M1234567L", "B64717838", "T85810679", "ES B64717838")
		for number in spanish_cases:
			self.assertTrue(validator.looks_spanish(number), number)
		non_spanish_cases = ("", "85810678", "FR12345678", "DE123456789", "1234567890")
		for number in non_spanish_cases:
			self.assertFalse(validator.looks_spanish(number), number)
