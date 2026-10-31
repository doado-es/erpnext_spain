# Fixtures propios e idempotentes para los tests de integración (spec 01 §8
# H8): los tests no dependen de los datos del sitio (compañía real, clientes
# o artículos de demostración). Cada helper crea el registro si no existe y
# devuelve su nombre; llamarlo varias veces es seguro.

from __future__ import annotations

import frappe

TEST_COMPANY = "_Test ES Company"
TEST_COMPANY_ABBR = "_TESC"
TEST_COMPANY_CIF = "B12345674"  # CIF con dígito de control correcto

TEST_CUSTOMER = "_Test ES Customer"
TEST_CUSTOMER_NIF = "12345678Z"  # NIF con letra de control correcta

TEST_ITEM = "_Test ES Item"

SIF_IDENTITY = {
	"sif_nombre_razon": "_Test ES Productor SIF SL",
	"sif_nif": "B58834813",
	"sif_nombre_sistema_informatico": "ERPNext Spain Test",
	"sif_id_sistema_informatico": "ET",
	"sif_version": "1.0",
}


def ensure_test_company() -> str:
	"""Compañía española de test (España, EUR, CIF válido). Se crea una vez
	y se reutiliza por nombre: el insert arrastra plan contable, almacenes y
	centros de coste, lo que resulta lento."""
	if not frappe.db.exists("Company", TEST_COMPANY):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": TEST_COMPANY,
				"abbr": TEST_COMPANY_ABBR,
				"country": "Spain",
				"default_currency": "EUR",
				"chart_of_accounts": "Standard",
				"tax_id": TEST_COMPANY_CIF,
			}
		).insert(ignore_permissions=True)
	return TEST_COMPANY


def ensure_test_customer() -> str:
	"""Cliente español de test con NIF válido."""
	if not frappe.db.exists("Customer", TEST_CUSTOMER):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": TEST_CUSTOMER,
				"customer_type": "Company",
				"customer_group": _first_leaf("Customer Group"),
				"territory": _first_leaf("Territory"),
				"tax_id": TEST_CUSTOMER_NIF,
			}
		).insert(ignore_permissions=True)
	return TEST_CUSTOMER


def ensure_test_item() -> str:
	"""Artículo de test sin control de stock."""
	if not frappe.db.exists("Item", TEST_ITEM):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": TEST_ITEM,
				"item_name": TEST_ITEM,
				"item_group": _first_leaf("Item Group"),
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
	return TEST_ITEM


def ensure_sif_identity() -> None:
	"""Rellena la identidad del SIF en ES Settings solo en los campos vacíos;
	no sobrescribe valores ya configurados en el sitio."""
	settings = frappe.get_single("ES Settings")
	missing = {field: value for field, value in SIF_IDENTITY.items() if not settings.get(field)}
	if missing:
		settings.update(missing)
		settings.save(ignore_permissions=True)


def _first_leaf(doctype: str) -> str:
	name = frappe.get_all(doctype, filters={"is_group": 0}, pluck="name", order_by="lft", limit=1)
	if name:
		return name[0]
	return frappe.get_all(doctype, pluck="name", order_by="lft", limit=1)[0]
