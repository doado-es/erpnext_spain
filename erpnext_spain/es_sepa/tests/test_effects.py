# Cálculo de efectos para las remesas (es_sepa/effects.py).

import frappe
from frappe.tests import UnitTestCase

from erpnext_spain.es_sepa import effects


def term(payment_term, payment_amount, outstanding):
	return frappe._dict(payment_term=payment_term, payment_amount=payment_amount, outstanding=outstanding)


class TestSplitOutstanding(UnitTestCase):
	def test_terms_up_to_date(self):
		rows = [term("30", 50, 0), term("60", 50, 50)]
		self.assertEqual(effects.split_outstanding(rows, 50), [0, 50])

	def test_payment_without_term_reduces_oldest(self):
		# Pago de 70 sin indicar el vencimiento: los plazos siguen a 50 y 50.
		rows = [term("30", 50, 50), term("60", 50, 50)]
		self.assertEqual(effects.split_outstanding(rows, 30), [0, 30])

	def test_rows_without_term_use_their_amount(self):
		rows = [term(None, 60.5, 0), term(None, 60.5, 0)]
		self.assertEqual(effects.split_outstanding(rows, 121), [60.5, 60.5])


class TestFilters(UnitTestCase):
	def effects(self):
		return [
			{"invoice": "A", "payment_term": "30", "due_date": "2026-11-30", "amount": 100},
			{"invoice": "A", "payment_term": "60", "due_date": "2026-12-30", "amount": 100},
			{"invoice": "B", "payment_term": None, "due_date": "2026-11-15", "amount": -20},
		]

	def test_subtract_reserved(self):
		result = effects.subtract_reserved(self.effects(), {("A", "30"): 100, ("A", "60"): 40, ("B", ""): -5})
		self.assertEqual(
			[(e["invoice"], e["payment_term"], e["amount"]) for e in result],
			[("A", "60", 60), ("B", None, -15)],
		)

	def test_in_range_by_date_and_absolute_amount(self):
		result = effects.in_range(self.effects(), to_due_date="2026-12-01", min_amount=10, max_amount=50)
		self.assertEqual([e["invoice"] for e in result], ["B"])

	def test_as_list(self):
		self.assertEqual(effects.as_list('["a", "b"]'), ["a", "b"])
		self.assertEqual(effects.as_list("a, b"), ["a", "b"])
		self.assertEqual(effects.as_list(None), [])
