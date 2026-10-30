# Tests de los estados PGC PYMES (spec 04, criterios 1-4, 6 y 8).

from __future__ import annotations

import json
import unittest

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_contabilidad import pgc
from erpnext_spain.es_contabilidad.chart_of_accounts import generate as chart_generator
from erpnext_spain.es_contabilidad.statements import generate_templates
from erpnext_spain.es_contabilidad.statements.mapping import TEMPLATE_NAMES, model_rows, prefixes

BALANCE = TEMPLATE_NAMES[("PYMES", "Balance")]
PYG = TEMPLATE_NAMES[("PYMES", "PyG")]


def chart_leaves(model: str) -> list[str]:
	meta = {"account_number", "account_type", "root_type", "is_group"}
	chart = json.loads((chart_generator.HERE / chart_generator.MODELS[model][1]).read_text(encoding="utf-8"))
	leaves = []

	def walk(tree):
		for name, node in tree.items():
			if name in meta:
				continue
			if set(node) - meta:
				walk(node)
			else:
				leaves.append(node["account_number"])

	walk(chart["tree"])
	return leaves


class TestMapping(unittest.TestCase):
	def test_templates_match_generator(self):
		"""Nadie edita las plantillas a mano: son la salida del generador."""
		for model, statement in TEMPLATE_NAMES:
			path = generate_templates.output_path(model, statement)
			self.assertEqual(
				path.read_text(encoding="utf-8"),
				generate_templates.render(generate_templates.generate(model, statement)),
				f"{path.name} no coincide con generate_templates.py; ejecútelo y commitee el resultado.",
			)

	def test_every_account_in_exactly_one_line(self):
		"""Cada cuenta del plan PYMES está en una sola partida (salvo las de signo,
		que están en dos: una por lado)."""
		for statement, groups in (("Balance", "12345"), ("PyG", "67")):
			rows = [r for r in model_rows("PYMES", statement) if r["tipo"] in ("cuentas", "signo")]
			for number in chart_leaves("PYMES"):
				if number[0] not in groups:
					continue
				hits = [r for r in rows if any(number.startswith(p) for p in prefixes(r["incluir"]))]
				with self.subTest(statement=statement, account=number):
					self.assertTrue(hits, f"{number} no está en ninguna partida")
					if len(hits) > 1:
						self.assertEqual(len(hits), 2, number)
						self.assertEqual({r["lado"] for r in hits}, {"deudor", "acreedor"}, number)
						for r in hits:
							self.assertTrue(any(number.startswith(p) for p in prefixes(r["segun_signo"])))

	def test_prefix_filters_are_anchored(self):
		for model, statement in TEMPLATE_NAMES:
			template = generate_templates.generate(model, statement)
			for row in template["rows"]:
				if row["data_source"] == "Account Data":
					self.assertNotIn('"like", "%', row["calculation_formula"], row["reference_code"])


class TestPYMESStatements(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = "_Test ES Estados PYMES"
		if not frappe.db.exists("Company", cls.company):
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": cls.company,
					"abbr": "_TEEP",
					"country": "Spain",
					"default_currency": "EUR",
					"chart_of_accounts": "Standard",
				}
			).insert()
		pgc.apply_pgc_chart(cls.company, "PYMES", dry_run=False)
		cls.customer = cls._party("Customer", "_Test ES Estados Cliente")
		cls.supplier = cls._party("Supplier", "_Test ES Estados Proveedor")
		cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
		cls._journal(
			[
				("1000", 0, 10000),  # capital
				("5720", 10000, 0),
			]
		)
		cls._journal([("2170", 3000, 0), ("5720", 0, 3000)])  # equipos informáticos
		cls._journal([("6810", 500, 0), ("2817", 0, 500)], "Depreciation Entry")  # amortización
		cls._journal([("4300", 2420, 0, "Customer", cls.customer), ("7000", 0, 2000), ("4770", 0, 420)])
		cls._journal([("6000", 400, 0), ("4720", 84, 0), ("4000", 0, 484, "Supplier", cls.supplier)])
		cls._journal([("4070", 200, 0, "Supplier", cls.supplier), ("5720", 0, 200)])  # anticipo a proveedor
		cls._journal([("5720", 300, 0), ("4380", 0, 300, "Customer", cls.customer)])  # anticipo de cliente
		cls._journal([("6230", 100, 0), ("4751", 0, 15), ("5720", 0, 85)])  # profesional con retención
		cls._journal([("5510", 50, 0), ("5720", 0, 50)])  # préstamo al socio: saldo deudor
		cls._journal([("5720", 700, 0), ("5523", 0, 700)])  # c/c con empresa del grupo: saldo acreedor

	@classmethod
	def _party(cls, doctype: str, name: str) -> str:
		if not frappe.db.exists(doctype, name):
			field = "customer_name" if doctype == "Customer" else "supplier_name"
			frappe.get_doc({"doctype": doctype, field: name}).insert()
		return name

	@classmethod
	def _journal(cls, lines: list[tuple], voucher_type: str = "Journal Entry") -> None:
		accounts = []
		for line in lines:
			number, debit, credit, *party = line
			accounts.append(
				{
					"account": pgc.account_by_number(cls.company, number),
					"debit_in_account_currency": debit,
					"credit_in_account_currency": credit,
					"cost_center": cls.cost_center,
					"party_type": party[0] if party else None,
					"party": party[1] if party else None,
				}
			)
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": voucher_type,
				"company": cls.company,
				"posting_date": frappe.utils.today(),
				"accounts": accounts,
			}
		)
		je.insert()
		je.submit()

	def _filters(self, template: str | None = None) -> frappe._dict:
		year = frappe.db.get_value(
			"Fiscal Year",
			{"year_start_date": ["<=", frappe.utils.today()], "year_end_date": [">=", frappe.utils.today()]},
		)
		return frappe._dict(
			company=self.company,
			filter_based_on="Fiscal Year",
			period_start_date=None,
			from_fiscal_year=year,
			to_fiscal_year=year,
			periodicity="Yearly",
			accumulated_values=1,
			report_template=template,
		)

	def _values(self, report: str, template: str) -> dict[str, float]:
		"""Valor del último periodo de cada fila, por código de la fila del mapeo."""
		module = frappe.get_module(f"erpnext.accounts.report.{report}.{report}")
		_, data, *_ = module.execute(self._filters(template))
		statement = "Balance" if template == BALANCE else "PyG"
		codes = {r["epigrafe"]: r["codigo"] for r in model_rows("PYMES", statement)}
		values = {}
		for row in data:
			code = codes.get(row.get("account"))
			keys = (row.get("_segment_info") or {}).get("period_keys") or []
			if code and keys:
				values[code] = row.get(keys[-1]) or 0
		return values

	def test_templates_synced(self):
		for name in (BALANCE, PYG):
			self.assertTrue(frappe.db.exists("Financial Report Template", name))

	def test_balance_balances(self):
		values = self._values("balance_sheet", BALANCE)
		self.assertAlmostEqual(values["TOTAL_ACTIVO"], values["TOTAL_PN_PASIVO"])
		# Igual al Balance nativo sin plantilla salvo las cuentas que se presentan
		# según su signo: la 5523 acreedora (700) está en la rama Activo del árbol
		# y la plantilla la lleva al pasivo.
		_, native, *_ = frappe.get_module("erpnext.accounts.report.balance_sheet.balance_sheet").execute(
			self._filters()
		)
		native_asset = next(r["total"] for r in native if r.get("account_name") == "Activo")
		self.assertAlmostEqual(values["TOTAL_ACTIVO"], native_asset + 700)

	def test_balance_lines(self):
		values = self._values("balance_sheet", BALANCE)
		self.assertAlmostEqual(values["ACT_A_II"], 2500)  # 3000 - 500 amortización
		self.assertAlmostEqual(values["ACT_B_I"], 200)  # anticipo a proveedor (407)
		self.assertAlmostEqual(values["ACT_B_II_1"], 2420)
		self.assertAlmostEqual(values["ACT_B_II_3"], 84)  # IVA soportado
		self.assertAlmostEqual(values["ACT_B_IV"], 50)  # 551 deudora en el activo
		self.assertAlmostEqual(values["PAS_C_III"], 700)  # 5523 acreedora en el pasivo
		self.assertAlmostEqual(values["ACT_B_III"], 0)  # y no en el activo
		self.assertAlmostEqual(values["PAS_C_II_3"], 0)  # 551 deudora no va al pasivo
		self.assertAlmostEqual(values["PAS_C_IV_1"], 484)
		self.assertAlmostEqual(values["PAS_C_IV_2"], 300 + 420 + 15)  # 438 + 477 + 4751
		self.assertAlmostEqual(values["PN_A1_I_1"], 10000)
		# Resultado del ejercicio sin cerrar: 2000 - 400 - 500 - 100.
		self.assertAlmostEqual(values["PN_A1_VII"], 1000)
		self.assertAlmostEqual(values["ACT_B_VI"], 10000 - 3000 - 200 + 300 - 85 - 50 + 700)

	def test_pyg_matches_native_result(self):
		values = self._values("profit_and_loss_statement", PYG)
		self.assertAlmostEqual(values["PYG_1"], 2000)
		self.assertAlmostEqual(values["PYG_4"], -400)
		self.assertAlmostEqual(values["PYG_7"], -100)
		self.assertAlmostEqual(values["PYG_8"], -500)
		self.assertAlmostEqual(values["PYG_D"], 1000)
