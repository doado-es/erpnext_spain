# Tests de los planes de cuentas PGC (spec 02 §1 y criterio de aceptación 1).

from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_contabilidad.chart_of_accounts import generate

CHART_DIR = Path(generate.__file__).resolve().parent
META = {"account_number", "account_type", "root_type", "is_group"}
MANDATORY_TYPES = {
	# get_mandatory_account_types del importador de planes de ERPNext v16.
	"Cost of Goods Sold": "Expense",
	"Depreciation": "Expense",
	"Fixed Asset": "Asset",
	"Payable": "Liability",
	"Receivable": "Asset",
	"Stock Adjustment": "Expense",
	"Bank": "Asset",
	"Cash": "Asset",
	"Stock": "Asset",
}


def load(model: str) -> dict:
	_, output, _ = generate.MODELS[model]
	return json.loads((CHART_DIR / output).read_text(encoding="utf-8"))


def walk(tree: dict):
	"""Recorre el árbol y devuelve (ruta, nombre, nodo, root_type, es_hoja, ancestros numerados)."""
	for root_name, root in tree.items():
		stack = [([root_name], root, [])]
		while stack:
			path, node, numbered = stack.pop()
			for name, child in node.items():
				if name in META:
					continue
				is_leaf = not (set(child) - META)
				number = child.get("account_number")
				yield [*path, name], child, root["root_type"], is_leaf, numbered
				stack.append(([*path, name], child, [*numbered, number] if number else numbered))


class TestChartFiles(unittest.TestCase):
	def test_committed_files_match_generator(self):
		"""Nadie edita los JSON a mano: deben ser la salida exacta del generador."""
		for model, (_, output, _) in generate.MODELS.items():
			committed = (CHART_DIR / output).read_text(encoding="utf-8")
			self.assertEqual(
				committed,
				generate.render(generate.generate(model)),
				f"{output} no coincide con generate.py; ejecute el generador y commitee el resultado.",
			)

	def test_structure(self):
		for model in generate.MODELS:
			with self.subTest(model=model):
				chart = load(model)
				self.assertEqual(chart["country_code"], "es")
				self.assertEqual(chart["version"], generate.VERSION)
				numbers = []
				leaves = 0
				for path, node, _root_type, is_leaf, numbered in walk(chart["tree"]):
					number = node.get("account_number")
					if number:
						numbers.append(number)
						# Cada número empieza por el de su antecesor numerado más cercano.
						if numbered:
							self.assertTrue(number.startswith(numbered[-1]), " > ".join(path))
						self.assertLessEqual(
							len(f"{number} - {path[-1]}"), generate.MAX_NUMBER_AND_NAME, " > ".join(path)
						)
					if is_leaf:
						leaves += 1
						# Opción B: se contabiliza en cuentas de 4 o 5 dígitos.
						self.assertIsNotNone(number, " > ".join(path))
						self.assertIn(len(number), (4, 5), number)
						self.assertEqual(generate.ROOTS[generate.root_of(number)], path[0], number)
				duplicated = [n for n, c in Counter(numbers).items() if c > 1]
				self.assertEqual(duplicated, [])
				self.assertGreater(leaves, 600)

	def test_mandatory_account_types(self):
		for model in generate.MODELS:
			chart = load(model)
			found = {
				(node.get("account_type"), root_type) for _, node, root_type, _, _ in walk(chart["tree"])
			}
			for account_type, root_type in MANDATORY_TYPES.items():
				self.assertIn((account_type, root_type), found, f"{model}: falta {account_type}")

	def test_branches_of_split_subgroups(self):
		"""Casos señalados en la spec 02 §1."""
		cases = {
			"4070": "Asset",
			"4060": "Liability",
			"4370": "Asset",
			"1034": "Liability",
			"1900": "Liability",
			"5550": "Liability",
			"5595": "Liability",
			"4380": "Liability",
			"4300": "Asset",
			"4000": "Liability",
			"4751": "Liability",
			"4720": "Asset",
			"5570": "Equity",
			"5720": "Asset",
			"1000": "Equity",
			"1700": "Liability",
			"6000": "Expense",
			"7000": "Income",
		}
		for number, root_type in cases.items():
			self.assertEqual(generate.root_of(number), root_type, number)

	def test_party_and_provisional_accounts(self):
		chart = load("PYMES")
		types = {node.get("account_number"): node.get("account_type") for _, node, *_ in walk(chart["tree"])}
		self.assertEqual(types["4300"], "Receivable")
		self.assertEqual(types["4380"], "Receivable")
		self.assertEqual(types["4000"], "Payable")
		self.assertEqual(types["4070"], "Payable")
		# Facturas pendientes de recibir/formalizar: sin tercero.
		for number in ("4009", "4109", "4309"):
			self.assertIsNone(types[number], number)
		self.assertEqual(types["572"], "Bank")
		self.assertEqual(types["5720"], "Bank")
		self.assertEqual(types["5700"], "Cash")

	def test_boe_name_fixes(self):
		chart = json.dumps(load("PYMES"), ensure_ascii=False)
		self.assertIn("Instalaciones técnicas en montaje", chart)
		self.assertNotIn("deterioroy", chart.lower())


class TestCreateCharts(IntegrationTestCase):
	"""Los dos planes se crean en una compañía con create_charts de ERPNext."""

	def _company(self, model: str) -> str:
		name = f"_Test ES Plan {model}"
		if not frappe.db.exists("Company", name):
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": name,
					"abbr": f"_TP{model[0]}",
					"country": "Spain",
					"default_currency": "EUR",
					"chart_of_accounts": "Standard",
				}
			).insert()
		return name

	def test_create_both_charts(self):
		from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import create_charts

		from erpnext_spain.es_contabilidad.pgc import clear_company_chart

		for model in generate.MODELS:
			with self.subTest(model=model):
				company = self._company(model)
				clear_company_chart(company)
				chart = load(model)
				create_charts(company, custom_chart=chart["tree"])

				accounts = frappe.get_all(
					"Account",
					filters={"company": company},
					fields=["account_number", "root_type", "is_group", "account_type"],
				)
				expected = sum(1 for _ in walk(chart["tree"])) + len(chart["tree"])
				self.assertEqual(len(accounts), expected)
				for account in accounts:
					if not account.is_group:
						self.assertTrue(account.account_number)
						self.assertEqual(account.root_type, generate.root_of(account.account_number))
				by_number = {a.account_number: a for a in accounts if a.account_number}
				self.assertEqual(by_number["4380"].root_type, "Liability")
				self.assertEqual(by_number["4380"].account_type, "Receivable")
				self.assertEqual(by_number["4070"].root_type, "Asset")
				self.assertEqual(by_number["4070"].account_type, "Payable")
