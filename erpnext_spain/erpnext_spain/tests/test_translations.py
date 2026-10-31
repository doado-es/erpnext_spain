# Comprobaciones del catálogo de traducciones es-ES de la app.

from __future__ import annotations

import re
import unittest
from pathlib import Path

from babel.messages.pofile import read_po

PO_FILE = Path(__file__).resolve().parents[2] / "locale" / "es.po"
PLACEHOLDERS = re.compile(r"\{\d*\}|%\(?\w*\)?s|\{\{.*?\}\}|\{%.*?%\}|<[^>]+>")


class TestSpanishCatalog(unittest.TestCase):
	def setUp(self):
		with PO_FILE.open("rb") as f:
			self.catalog = read_po(f)

	def test_all_entries_translated(self):
		empty = [m.id for m in self.catalog if m.id and not m.string]
		self.assertEqual(empty, [])

	def test_placeholders_preserved(self):
		"""Los marcadores ({0}, %s, Jinja, HTML) deben ser los mismos en el original y la traducción."""
		for message in self.catalog:
			if not message.id:
				continue
			with self.subTest(msgid=message.id[:60]):
				self.assertEqual(
					sorted(PLACEHOLDERS.findall(message.id)), sorted(PLACEHOLDERS.findall(message.string))
				)

	def test_spanish_accounting_terms(self):
		translations = {m.id: m.string for m in self.catalog if m.id and not m.context}
		self.assertEqual(translations["General Ledger"], "Libro mayor")
		self.assertEqual(translations["Trial Balance"], "Balance de sumas y saldos")
		self.assertEqual(translations["Chart of Accounts"], "Plan de cuentas")

	def test_spain_terms_in_compound_strings(self):
		"""Cadenas compuestas de ERPNext con la terminología de España (bloque 9)."""
		translations = {m.id: m.string for m in self.catalog if m.id and not m.context}
		self.assertEqual(translations["Creating Delivery Note ..."], "Creando albarán...")
		self.assertIn(
			"del pedido de compra",
			translations[
				"<p>Posting Date {0} cannot be before Purchase Order date for the following:</p><ul>"
			],
		)
		self.assertEqual(translations["All Items"], "Todos los artículos")

	def test_app_doctypes_translated(self):
		import json

		root = PO_FILE.parents[1]
		translations = {m.id for m in self.catalog if m.id}
		for path in root.glob("*/doctype/*/*.json"):
			name = json.loads(path.read_text(encoding="utf-8")).get("name")
			with self.subTest(doctype=name):
				self.assertIn(name, translations)
