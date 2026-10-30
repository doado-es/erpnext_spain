# Site tests del catálogo «ES Invoice Type» (spec 04 §2.1):
# catálogo completo (F1-F3, R1-R5) con la semántica VERIFICADA contra el XSD
# oficial de la AEAT (SuministroInformacion.xsd, Orden HAC/1177/2024), semilla
# idempotente y SIN series globales (defecto corregido de la referencia).

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_verifactu.catalog import INVOICE_TYPE_CATALOG, seed_invoice_types

DOCTYPE = "ES Invoice Type"

RECTIFICATIVE_CODES = ("R1", "R2", "R3", "R4", "R5")
ORDINARY_CODES = ("F1", "F2", "F3")


class TestInvoiceTypeCatalog(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# El catálogo se siembra en after_migrate; el test lo re-sincroniza para
		# ser autónomo en instalaciones donde el wiring aún no corrió.
		seed_invoice_types()

	def test_catalog_complete_and_synced(self):
		self.assertEqual(
			{e["code"] for e in INVOICE_TYPE_CATALOG},
			{"F1", "F2", "F3", *RECTIFICATIVE_CODES},
		)
		for entry in INVOICE_TYPE_CATALOG:
			doc = frappe.get_doc(DOCTYPE, entry["code"])
			self.assertEqual(doc.label, entry["label"], entry["code"])
			self.assertEqual(doc.is_simplified, entry["is_simplified"], entry["code"])
			self.assertEqual(doc.rectification_type or "", entry["rectification_type"], entry["code"])

	def test_exactly_eight_catalog_types(self):
		names = set(frappe.get_all(DOCTYPE, pluck="name"))
		self.assertTrue({e["code"] for e in INVOICE_TYPE_CATALOG} <= names)
		# una fila por código (el docname ES el código: sin duplicados)
		for codigo in (e["code"] for e in INVOICE_TYPE_CATALOG):
			self.assertEqual(frappe.get_all(DOCTYPE, filters={"name": codigo}, pluck="name"), [codigo])

	def test_f2_and_r5_are_simplified(self):
		# F2 = factura simplificada; R5 = rectificativa DE SIMPLIFICADAS (XSD
		# AEAT). R4 («resto») es rectificativa de ordinarias: no lo es.
		self.assertEqual(frappe.db.get_value(DOCTYPE, "F2", "is_simplified"), 1)
		self.assertEqual(frappe.db.get_value(DOCTYPE, "R5", "is_simplified"), 1)
		for codigo in ("F1", "F3", "R1", "R2", "R3", "R4"):
			self.assertEqual(frappe.db.get_value(DOCTYPE, codigo, "is_simplified"), 0, codigo)

	def test_rectificatives_with_type_ordinaries_without(self):
		for codigo in RECTIFICATIVE_CODES:
			self.assertIn(frappe.db.get_value(DOCTYPE, codigo, "rectification_type"), ("S", "I"), codigo)
		for codigo in ORDINARY_CODES:
			self.assertFalse(frappe.db.get_value(DOCTYPE, codigo, "rectification_type"), codigo)

	def test_no_global_series(self):
		"""El catálogo queda SOLO como códigos/semántica (spec 04 §2.1): las
		series viven por empresa en el mapeo (defecto de la referencia
		corregido)."""
		meta = frappe.get_meta(DOCTYPE)
		self.assertIsNone(meta.get_field("series"))
		self.assertIsNotNone(frappe.get_meta("Company").get_field("es_invoice_series"))

	def test_seed_idempotent(self):
		seed_invoice_types()
		seed_invoice_types()
		for entry in INVOICE_TYPE_CATALOG:
			self.assertEqual(
				len(frappe.get_all(DOCTYPE, filters={"name": entry["code"]}, pluck="name")), 1
			)

	def test_code_unique(self):
		# el docname ES el código (autoname field:code): otra «F1» rebota
		duplicado = frappe.get_doc({"doctype": DOCTYPE, "code": "F1", "label": "Otra F1"})
		with self.assertRaises(frappe.DuplicateEntryError):
			duplicado.insert(ignore_permissions=True)

	def test_code_normalized(self):
		doc = frappe.get_doc(
			{"doctype": DOCTYPE, "code": " t9 ", "label": "Tipo de prueba"}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.code, "T9")
