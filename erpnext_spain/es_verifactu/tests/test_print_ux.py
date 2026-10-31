# Tests del lote 6a — QR/jinja/print/UX (spec 04 §11 + doc 12 §13/§14):
# helpers Jinja del Print Format (URL ValidarQR por modo, SVG segno, desglose
# formateado, denominación display spec 14), materializado del Print Format +
# Property Setter default_print_format (idempotencia del migrate) y smoke de
# render con el jenv real de impresión.
#
# Misma convención que test_emision_registros.py: módulo en tests/, masters
# reales del site (localized), rollback POR CLASE con reset de la compañía en
# setUp (db.set_value sin hooks) y libro vaciado por db.delete.

from __future__ import annotations

import glob
import os
from urllib.parse import quote

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from erpnext_spain.aeat.tests.helpers import (
	clean_pem,
	generate_p12,
	test_company,
	write_private_p12,
)
from erpnext_spain.aeat.utils import absolute_site_path, format_aeat_date
from erpnext_spain.es_verifactu.emission import VERIFACTU_MODE, VERIFACTU_TEST_MODE
from erpnext_spain.es_verifactu.printing import FORMAT_NAME, setup_printing
from erpnext_spain.es_verifactu.utils.jinja import (
	QR_URL_BASE_PRODUCCION,
	QR_URL_BASE_PRUEBAS,
	get_es_display_name,
	get_verifactu_breakup,
	get_verifactu_qr_code,
	get_verifactu_qr_url,
)
from erpnext_spain.tests.fixtures import TEST_CUSTOMER, TEST_ITEM

VALID_NIF = "12345678Z"
ACTIVATION_DATE = "2026-01-01"
INVOICE_DATE = "2026-08-31"

DRAFT_SERIES = "BORRADOR-.#####"
F1_SERIES = "SIF1-.####."

CUSTOMER = TEST_CUSTOMER
ITEM = TEST_ITEM

LEDGER_DOCTYPE = "ES Verifactu Billing Record"
P12_PATTERN = "es_test_print_*.p12"
PASSWORD = "es-test-pass"


def _delete_test_p12() -> None:
	for path in glob.glob(absolute_site_path("private", "files", P12_PATTERN)):
		os.remove(path)


def _reset_company(company: str) -> None:
	"""Compañía a estado prístino (mismo reset que test_emision_registros)."""
	frappe.set_user("Administrator")
	frappe.db.set_value(
		"Company",
		company,
		{
			"es_verifactu_enabled": 0,
			"es_verifactu_activation_date": None,
			"es_verifactu_credential": None,
			"es_draft_series": None,
			"es_verifactu_remission_mode": None,
			"es_verifactu_noi": None,
			"tax_id": None,
		},
	)
	frappe.db.delete("ES Invoice Series", {"parent": company})
	frappe.db.delete("ES Verifactu Notification Role", {"parent": company})
	frappe.db.delete(LEDGER_DOCTYPE, {"company": company})
	for credential in frappe.get_all("ES AEAT Credential", filters={"company": company}, pluck="name"):
		frappe.delete_doc("ES AEAT Credential", credential, ignore_permissions=True)


def _activate_verifactu(company: str, test_mode: str = "Pruebas"):
	"""Deja la compañía ACTIVA con mapeo F1 y el modo pedido (credencial
	exigida por before_submit — mismo fixture que test_emision_registros)."""
	clean_pem(company, "VeriFactu")
	doc = frappe.get_doc("Company", company)
	doc.tax_id = VALID_NIF
	doc.es_verifactu_enabled = 1
	doc.es_verifactu_activation_date = ACTIVATION_DATE
	doc.es_verifactu_test_mode = test_mode
	doc.es_draft_series = DRAFT_SERIES
	doc.es_verifactu_remission_mode = "Diferida"
	doc.set("es_invoice_series", [])
	doc.append("es_invoice_series", {"series": F1_SERIES, "invoice_type": "F1"})
	url = write_private_p12(
		f"es_test_print_{frappe.generate_hash(length=8)}.p12", generate_p12(password=PASSWORD.encode())[0]
	)
	frappe.get_doc(
		{
			"doctype": "ES AEAT Credential",
			"company": company,
			"purpose": "VeriFactu",
			"cert_file": url,
			"cert_password": PASSWORD,
			"enabled": 1,
		}
	).insert(ignore_permissions=True)
	doc.save(ignore_permissions=True)
	return doc


def _invoice(company: str, vat_account: str, **overrides):
	"""Factura mínima de la compañía de pruebas (descripción «IVA - 21» =
	patrón del contrato 07 que parsea el lóbulo del desglose). El insert corre
	calculate_taxes_and_totals — net_amount/tax_amount quedan en las filas."""
	data = {
		"doctype": "Sales Invoice",
		"company": company,
		"customer": CUSTOMER,
		"naming_series": "ACC-SINV-.YYYY.-",
		"currency": "EUR",
		"posting_date": INVOICE_DATE,
		"set_posting_time": 1,
		"due_date": add_days(nowdate(), 30),
		"items": [{"item_code": ITEM, "qty": 1, "rate": 100}],
		"taxes": [
			{
				"charge_type": "On Net Total",
				"account_head": vat_account,
				"rate": 21,
				"description": "IVA - 21",
			}
		],
	}
	data.update(overrides)
	return frappe.get_doc(data).insert(ignore_permissions=True)


def _vat_account(company: str) -> str:
	return frappe.db.get_value(
		"Account", {"company": company, "account_type": "Tax", "is_group": 0}, "name"
	)


# ---------------------------------------------------------------------------
# URL/QR de validación por modo operativo (spec 04 §11)
# ---------------------------------------------------------------------------


class TestJinjaQR(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.vat_account = _vat_account(cls.company)
		_delete_test_p12()  # restos de corridas abortadas
		cls.addClassCleanup(_delete_test_p12)
		cls.addClassCleanup(clean_pem, cls.company, "VeriFactu")

	def setUp(self):
		_reset_company(self.company)

	# --- URL/QR por modo (spec 04 §11) --------------------------------------

	def test_qr_invoice_test_mode_url_and_svg(self):
		"""Factura emitida con la compañía en Pruebas: snapshot
		«Verifactu en pruebas» → URL con la base de PRUEBAS de la AEAT, los
		cuatro parámetros en el orden del spec (nif, fecha dd-mm-aaaa,
		importe, numserie) y el SVG de segno del código."""
		_activate_verifactu(self.company, test_mode="Pruebas")
		a = _invoice(self.company, self.vat_account)
		a.submit()

		self.assertEqual(a.es_verifactu_mode, VERIFACTU_TEST_MODE)
		url = get_verifactu_qr_url(a)
		self.assertTrue(url.startswith(QR_URL_BASE_PRUEBAS), url)
		# parámetros exactos del spec 04 §11 (orden nif, fecha, importe, numserie)
		self.assertIn(f"nif={VALID_NIF}", url)
		# before_submit mantiene posting_date=hoy: se aserta contra el valor
		# REAL de la factura (dd-mm-aaaa, el formato AEAT del QR)
		self.assertIn(f"fecha={format_aeat_date(a.posting_date)}", url)
		# importe con el formato de monto congelado del adaptador
		self.assertIn(f"importe={str(float(a.rounded_total))}", url)
		self.assertIn(f"numserie={a.name}", url)

		svg = get_verifactu_qr_code(a)
		self.assertIn("<svg", svg)
		self.assertIn("class=\"segno\"", svg)  # marca del QR generado
		# el SVG es reproducible: mismo input → mismo código
		self.assertEqual(svg, get_verifactu_qr_code(frappe.get_doc("Sales Invoice", a.name)))

	def test_qr_invoice_production(self):
		"""Snapshot «Verifactu» → URL con la base de PRODUCCIÓN (el dominio
		real agenciatributaria.gob.es). La base NO cambia si la compañía pasa
		a pruebas DESPUÉS de emitir: el snapshot congelado manda (spec §2.3)."""
		_activate_verifactu(self.company, test_mode="Producción")
		a = _invoice(self.company, self.vat_account)
		a.submit()
		self.assertEqual(a.es_verifactu_mode, VERIFACTU_MODE)

		url = get_verifactu_qr_url(a)
		self.assertTrue(url.startswith(QR_URL_BASE_PRODUCCION), url)
		self.assertIn(f"nif={VALID_NIF}", url)

		# la compañía pasa a pruebas DESPUÉS de emitir: el snapshot manda
		frappe.db.set_value("Company", self.company, "es_verifactu_test_mode", "Pruebas")
		self.assertTrue(get_verifactu_qr_url(a).startswith(QR_URL_BASE_PRODUCCION))

	def test_qr_without_verifactu_empty(self):
		"""Factura de una compañía SIN VeriFactu (sin snapshot, sin fallback):
		URL y QR vacíos — no hay nada validable en la AEAT."""
		a = _invoice(self.company, self.vat_account)
		a.submit()
		self.assertFalse(a.get("es_verifactu_mode"))

		self.assertEqual(get_verifactu_qr_url(a), "")
		self.assertEqual(get_verifactu_qr_code(a), "")

	def test_qr_draft_falls_back_to_current_company_state(self):
		"""Borrador (sin snapshot): fallback al estado ACTUAL de la compañía
		activa en pruebas → base de pruebas (el QR del borrador NO se
		imprime: la plantilla solo muestra el bloque VeriFactu ya emitida)."""
		_activate_verifactu(self.company, test_mode="Pruebas")
		a = _invoice(self.company, self.vat_account)
		self.assertEqual(a.docstatus, 0)

		url = get_verifactu_qr_url(a)
		self.assertTrue(url.startswith(QR_URL_BASE_PRUEBAS), url)
		# compañía inactiva → sin QR (el setUp la dejó desactivada)
		frappe.db.set_value("Company", self.company, "es_verifactu_enabled", 0)
		self.assertEqual(get_verifactu_qr_url(a), "")

	def test_qr_series_urlencoded(self):
		"""El numserie viaja URL-encodeado (safe=""): una serie con «/» no
		rompe la URL de validación."""
		_activate_verifactu(self.company, test_mode="Pruebas")
		a = _invoice(self.company, self.vat_account)
		a.submit()
		# nombre con carácter reservado por la vía del doc en memoria
		doc = frappe.get_doc("Sales Invoice", a.name)
		doc.name = f"{a.name}/2026"
		url = get_verifactu_qr_url(doc)
		self.assertIn(f"numserie={quote(doc.name, safe='')}", url)


# ---------------------------------------------------------------------------
# helpers de plantilla: desglose + denominación display (spec 04 §11/§14)
# ---------------------------------------------------------------------------


class TestJinjaHelpers(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.vat_account = _vat_account(cls.company)

	def setUp(self):
		frappe.set_user("Administrator")

	def test_breakup_rows_formatted(self):
		"""El desglose reutiliza el MISMO contrato del RegistroAlta (spec 04
		§7) con formato de display: importes con fmt_money de la moneda."""
		rows = get_verifactu_breakup(_invoice(self.company, self.vat_account))
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax"], "IVA")
		self.assertEqual(rows[0]["rate"], "21%")
		self.assertIn("100.00", rows[0]["base"])
		self.assertIn("21.00", rows[0]["tax_amount"])

	def test_breakup_unknown_tax_does_not_crash(self):
		"""Impuesto fuera del contrato 07 (p. ej. IRPF): la IMPRESIÓN no se
		rompe — fila omitida (impresión degradada, no error)."""
		doc = _invoice(self.company, self.vat_account)
		doc.taxes[0].description = "IRPF - 15"
		self.assertEqual(get_verifactu_breakup(doc), [])

	def test_display_name_with_trade_name(self):
		"""spec 14: «NombreComercial (RazónSocial)» cuando el maestro trae
		nombre comercial; se restaura el valor previo para no envenenar la
		clase (mismo patrón que el test de NIF del cliente)."""
		previous = frappe.db.get_value("Customer", CUSTOMER, "es_trade_name")
		frappe.db.set_value("Customer", CUSTOMER, "es_trade_name", "La Palmera SL")
		try:
			doc = _invoice(self.company, self.vat_account)
			self.assertEqual(get_es_display_name(doc, "customer"), f"La Palmera SL ({CUSTOMER})")
		finally:
			frappe.db.set_value("Customer", CUSTOMER, "es_trade_name", previous)

	def test_display_name_without_trade_name(self):
		"""Sin nombre comercial: la razón social a secas (el nombre comercial
		NUNCA fluye a la AEAT — display only)."""
		previous = frappe.db.get_value("Customer", CUSTOMER, "es_trade_name")
		frappe.db.set_value("Customer", CUSTOMER, "es_trade_name", None)
		try:
			doc = _invoice(self.company, self.vat_account)
			self.assertEqual(get_es_display_name(doc, "customer"), CUSTOMER)
		finally:
			frappe.db.set_value("Customer", CUSTOMER, "es_trade_name", previous)


# ---------------------------------------------------------------------------
# Print Format + Property Setter (doc 12 §13) + render smoke (doc 12 §14)
# ---------------------------------------------------------------------------


class TestPrintFormat(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.vat_account = _vat_account(cls.company)
		_delete_test_p12()
		cls.addClassCleanup(_delete_test_p12)
		cls.addClassCleanup(clean_pem, cls.company, "VeriFactu")
		# el materializador es idempotente: correrlo AQUÍ deja la clase
		# autocontenida (fresh site o site ya migrado — mismo resultado) y
		# YA verifica la doble corrida sin duplicados
		setup_printing()
		setup_printing()

	def setUp(self):
		_reset_company(self.company)

	def test_format_exists_and_is_custom_jinja(self):
		"""El registro Print Format existe, es Jinja custom completo y
		apunta a Sales Invoice (módulo ES Verifactu)."""
		format_doc = frappe.get_doc("Print Format", FORMAT_NAME)
		self.assertEqual(format_doc.doc_type, "Sales Invoice")
		self.assertEqual(format_doc.module, "ES Verifactu")
		self.assertEqual(format_doc.print_format_type, "Jinja")
		self.assertEqual(format_doc.custom_format, 1)
		self.assertIn("get_verifactu_qr_code", format_doc.html)

	def test_property_setter_default_print_format(self):
		"""default_print_format de Sales Invoice = nuestro formato, con
		is_system_generated=False y UN solo setter (setUpClass corrió
		setup_printing DOS veces: sin duplicados)."""
		setters = frappe.get_all(
			"Property Setter",
			filters={"doc_type": "Sales Invoice", "property": "default_print_format"},
			fields=["name", "value", "is_system_generated"],
		)
		self.assertEqual(len(setters), 1)
		self.assertEqual(setters[0].value, FORMAT_NAME)
		self.assertEqual(setters[0].is_system_generated, 0)

		# el meta del doctype lo sirve como default real
		self.assertEqual(frappe.get_meta("Sales Invoice").default_print_format, FORMAT_NAME)

	def test_render_draft_labeled(self):
		"""Render con el jenv REAL de impresión de un BORRADOR: sin
		excepciones, rotulado «NO ES FACTURA — BORRADOR» (spec 04 §4) y SIN
		bloque VeriFactu (el QR referencia el número fiscal final)."""
		draft = _invoice(self.company, self.vat_account)

		format_doc = frappe.get_doc("Print Format", FORMAT_NAME)
		render = frappe.render_template(format_doc.html, {"doc": draft})

		self.assertIn("NO ES FACTURA", render)
		self.assertIn('class="rotulo-borrador"', render)  # el rótulo del borrador
		self.assertNotIn("class=\"segno\"", render)  # sin QR en borradores
		self.assertIn(draft.name, render)

	def test_render_submitted_invoice_with_qr(self):
		"""Render de una factura EMITIDA (VeriFactu en pruebas): sin
		excepciones, con el bloque legal — el SVG del QR (marca segno), el
		enlace de validación y el estado denormalizado."""
		_activate_verifactu(self.company, test_mode="Pruebas")
		invoice = _invoice(self.company, self.vat_account)
		invoice.submit()
		invoice = frappe.get_doc("Sales Invoice", invoice.name)

		format_doc = frappe.get_doc("Print Format", FORMAT_NAME)
		render = frappe.render_template(format_doc.html, {"doc": invoice})

		self.assertIn("class=\"segno\"", render)  # QR (SVG inline de segno)
		self.assertIn(QR_URL_BASE_PRUEBAS, render)  # enlace de validación
		self.assertIn("Pendiente Envío", render)  # estado denormalizado
		self.assertIn(invoice.name, render)
		# sin rótulo de borrador (el DIV: el CSS y el comentario de cabecera
		# de la plantilla mencionan la clase/docs — no son el rótulo en sí)
		self.assertNotIn('class="rotulo-borrador"', render)
