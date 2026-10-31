# Norma 43, emparejamiento y agregador bancario (spec 13, criterios 1-7).

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, nowdate

from erpnext_spain.es_bancos import aggregator, importer, norma43
from erpnext_spain.es_sepa.tests.test_sepa import SepaTestCase, make_iban


def amount_field(value: float) -> str:
	return f"{round(abs(value) * 100):014d}"


def yymmdd(value) -> str:
	return getdate(value).strftime("%y%m%d")


def norma43_file(blocks: list[dict]) -> bytes:
	"""Fichero Norma 43 sintético: [{"ccc": entidad+oficina+cuenta, "opening": x,
	"movements": [(fecha, importe, concepto, referencia)]}]."""
	lines = []
	for block in blocks:
		bank, office, account = block["ccc"][:4], block["ccc"][4:8], block["ccc"][10:]
		opening = block["opening"]
		start = block["movements"][0][0] if block["movements"] else nowdate()
		lines.append(
			f"11{bank}{office}{account}{yymmdd(start)}{yymmdd(nowdate())}{'2' if opening >= 0 else '1'}"
			f"{amount_field(opening)}9783{'CUENTA PRUEBAS':<26}   "
		)
		debit = credit = 0.0
		debit_n = credit_n = 0
		for day, value, concept, reference in block["movements"]:
			key = "2" if value > 0 else "1"
			if value > 0:
				credit, credit_n = credit + value, credit_n + 1
			else:
				debit, debit_n = debit - value, debit_n + 1
			lines.append(
				f"22    {office}{yymmdd(day)}{yymmdd(day)}{concept}001{key}{amount_field(value)}{'0000000001':10}"
				f"{reference[:12]:<12}{reference[12:28]:<16}"
			)
			lines.append(f"2301{'MOVIMIENTO DE PRUEBA':<38}{reference:<38}")
		closing = opening + credit - debit
		lines.append(
			f"33{bank}{office}{account}{debit_n:05d}{amount_field(debit)}{credit_n:05d}{amount_field(credit)}"
			f"{'2' if closing >= 0 else '1'}{amount_field(closing)}978    "
		)
	lines.append(f"88{'9' * 18}{len(lines):06d}{' ' * 54}")
	return ("\r\n".join(line.ljust(80)[:80] for line in lines) + "\r\n").encode("latin-1")


class TestNorma43Parser(IntegrationTestCase):
	def test_totals_checked(self):
		content = norma43_file(
			[
				{
					"ccc": "21000418450200051332",
					"opening": 100,
					"movements": [(nowdate(), -30, "17", "COMISION")],
				}
			]
		)
		block = norma43.parse(content)[0]
		self.assertEqual(block.errors, [])
		self.assertEqual(block.closing, 70)
		broken = content.replace(b"000000000070", b"000000000099", 1)
		self.assertTrue(norma43.parse(broken)[0].errors)


class TestNorma43Import(SepaTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.caixa = cls.company_account
		ledger = frappe.db.get_value("Account", {"company": cls.company, "account_number": "5721"}, "name")
		if not ledger:
			parent = frappe.db.get_value("Account", {"company": cls.company, "account_number": "572"}, "name")
			ledger = (
				frappe.get_doc(
					{
						"doctype": "Account",
						"company": cls.company,
						"account_name": "Banco Santander",
						"account_number": "5721",
						"parent_account": parent,
						"account_type": "Bank",
					}
				)
				.insert()
				.name
			)
		cls.santander = cls.bank_account(
			"Cuenta Santander", make_iban("00490001500051234567"), company_account=ledger
		)

	def ccc(self, bank_account: str) -> str:
		iban = frappe.db.get_value("Bank Account", bank_account, "iban")
		return iban[4:24]

	def test_two_banks_and_reimport(self):
		"""Criterios 1 y 2: dos entidades; saldo final = registro 33; reimportar no duplica."""
		content = norma43_file(
			[
				{
					"ccc": self.ccc(self.caixa),
					"opening": 1000,
					"movements": [(nowdate(), 250, "04", "TRANSF1"), (nowdate(), -40, "17", "COMISION")],
				},
				{
					"ccc": self.ccc(self.santander),
					"opening": 0,
					"movements": [(nowdate(), -15.5, "12", "TARJETA")],
				},
			]
		)
		summary = importer.import_norma43(self.company, content)
		self.assertEqual(summary["created"], 3)
		self.assertEqual(summary["errors"], [])
		closing = {row["bank_account"]: row["closing_balance"] for row in summary["accounts"]}
		self.assertAlmostEqual(closing[self.caixa], 1210)
		self.assertAlmostEqual(closing[self.santander], -15.5)
		again = importer.import_norma43(self.company, content)
		self.assertEqual(again["created"], 0)
		self.assertEqual(again["duplicates"], 3)

	def test_unknown_account_reported(self):
		"""Criterio 3."""
		content = norma43_file(
			[
				{
					"ccc": self.ccc(self.caixa),
					"opening": 0,
					"movements": [(add_days(nowdate(), -1), 10, "04", "OTRA")],
				},
				{
					"ccc": "99990001000000000001",
					"opening": 0,
					"movements": [(nowdate(), 10, "04", "X")],
				},
			]
		)
		summary = importer.import_norma43(self.company, content)
		self.assertEqual(summary["created"], 1)
		self.assertEqual(len(summary["errors"]), 1)
		self.assertIn("9999 0001 0000000001", summary["errors"][0])

	def test_direct_debit_matched_by_end_to_end_id(self):
		"""Criterio 4: el cobro de la remesa se casa solo por el EndToEndId."""
		customer, account = self.party("Customer", "_Test ES Cliente N43", "21000418450200051414")
		mandate = frappe.get_doc(
			{
				"doctype": "ES Sepa Mandate",
				"mandate_reference": "MND-N43-1",
				"company": self.company,
				"customer": customer,
				"bank_account": account,
				"scheme": "CORE",
				"signature_date": add_days(nowdate(), -10),
			}
		).insert()
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": customer,
				"debit_to": frappe.db.get_value(
					"Account", {"company": self.company, "account_number": "4300"}
				),
				"cost_center": self.cost_center,
				"due_date": nowdate(),
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"rate": 80,
						"income_account": frappe.db.get_value(
							"Account", {"company": self.company, "account_number": "7050"}
						),
						"cost_center": self.cost_center,
					}
				],
			}
		).insert()
		si.submit()
		batch = frappe.get_doc(
			{
				"doctype": "ES Sepa Direct Debit Batch",
				"company": self.company,
				"bank_account": self.caixa,
				"scheme": "CORE",
				"collection_date": nowdate(),
				"lines": [{"sales_invoice": si.name, "mandate": mandate.name, "amount": 80}],
			}
		).insert()
		batch.submit()
		batch.reload()
		end_to_end = batch.lines[0].end_to_end_id
		content = norma43_file(
			[{"ccc": self.ccc(self.caixa), "opening": 0, "movements": [(nowdate(), 80, "03", end_to_end)]}]
		)
		importer.import_norma43(self.company, content)
		transaction = frappe.get_doc("Bank Transaction", {"reference_number": ["like", f"%{end_to_end}%"]})
		self.assertEqual(transaction.party, customer)
		self.assertEqual(
			[row.payment_entry for row in transaction.payment_entries], [batch.lines[0].payment_entry]
		)
		self.assertEqual(transaction.status, "Reconciled")

	def test_party_from_iban(self):
		"""Criterio 5."""
		supplier, account = self.party("Supplier", "_Test ES Proveedor IBAN", "21000418450200051423")
		iban = frappe.db.get_value("Bank Account", account, "iban")
		transaction = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"date": nowdate(),
				"company": self.company,
				"bank_account": self.caixa,
				"withdrawal": 12,
				"bank_party_iban": iban,
				"description": "Pago",
			}
		).insert()
		self.assertEqual((transaction.party_type, transaction.party), ("Supplier", supplier))


class TestAggregator(SepaTestCase):
	def test_sync_and_credentials(self):
		"""Criterios 6 y 7."""
		if not frappe.db.exists("ES Bank Aggregator", "_Test Agregador"):
			frappe.get_doc(
				{
					"doctype": "ES Bank Aggregator",
					"aggregator_name": "_Test Agregador",
					"company": self.company,
					"provider": aggregator.SIMULATED,
					"client_id": "cliente",
					"client_secret": "muy-secreto",
				}
			).insert()
		frappe.db.set_value("Bank Account", self.company_account, "es_bank_aggregator", "_Test Agregador")
		aggregator.start_consent(self.company_account)
		self.assertTrue(frappe.db.get_value("Bank Account", self.company_account, "integration_id"))
		frappe.flags.es_simulated_transactions = {
			self.company_account: [
				aggregator.AggregatorTransaction("A1", getdate(nowdate()), 45.0, "Cobro"),
				aggregator.AggregatorTransaction("A2", getdate(nowdate()), -9.9, "Comisión"),
			]
		}
		try:
			self.assertEqual(aggregator.sync_bank_account(self.company_account), 2)
			self.assertEqual(aggregator.sync_bank_account(self.company_account), 0)
		finally:
			frappe.flags.es_simulated_transactions = None
		from frappe.client import get as client_get

		data = client_get("ES Bank Aggregator", "_Test Agregador")
		self.assertNotIn("muy-secreto", frappe.as_json(data))
		self.assertEqual(flt(frappe.db.count("Bank Transaction", {"transaction_id": ["like", "AGG-%"]})), 2)
