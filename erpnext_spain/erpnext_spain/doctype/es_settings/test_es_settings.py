# Copyright (c) 2026, ct.galega and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestESSettings(IntegrationTestCase):
	def test_single_carga_con_defaults(self):
		doc = frappe.get_doc("ES Settings")
		self.assertEqual(doc.modo_validacion_nif, "Bloquear")

	def test_endpoints_oficiales_tras_la_instalacion(self):
		doc = frappe.get_doc("ES Settings")
		self.assertTrue(doc.verifactu_wsdl_test.startswith("https://prewww2.aeat.es/"))
		self.assertTrue(doc.verifactu_wsdl_production.startswith("https://www2.agenciatributaria.gob.es/"))

	def test_permisos_system_manager(self):
		"""Regresión: ES Settings nació con «permissions: []» — un doctype
		sin filas DocPerm queda INVISIBLE en el Desk (el router del SPA arma
		las rutas desde frappe.boot.user.can_read, que se deriva de DocPerm;
		los tests en verde no lo detectaban porque Administrator hace bypass
		de permisos). Ningún Single de la app puede volver a embarcar sin
		permisos."""
		meta = frappe.get_meta("ES Settings")
		sm = [p for p in (meta.permissions or []) if p.role == "System Manager"]
		self.assertTrue(sm, "ES Settings debe tener permisos para System Manager")
		self.assertTrue(sm[0].read and sm[0].write)

	def test_ningun_doctype_propio_sin_permisos(self):
		"""Barrido global de la misma lección: todo doctype de la app que no
		sea child table (istable) debe tener al menos una fila DocPerm —
		sinónimo de «existe pero inaccesible» (404 en el Desk para todos)."""
		modulos = {"ERPNext Spain", "Nif", "Aeat", "ES Verifactu"}
		doctypes = frappe.get_all(
			"DocType",
			filters={"module": ("in", sorted(modulos)), "istable": 0},
			pluck="name",
		)
		sin_permisos = [
			dt for dt in doctypes if not frappe.get_all("DocPerm", filters={"parent": dt}, limit=1)
		]
		self.assertEqual(sin_permisos, [])
