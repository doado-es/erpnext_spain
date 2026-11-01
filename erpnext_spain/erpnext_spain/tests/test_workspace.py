# Workspace «España», barra lateral, dock y onboarding de la localización.

import json

import frappe
from frappe.tests import IntegrationTestCase

EXPECTED_STEPS = [
	"ES Company Tax Data",
	"ES Apply PGC Chart",
	"ES AEAT Certificate",
	"ES Billing System",
	"ES Software Data",
	"ES Invoice Series",
	"ES Review Tax Templates",
	"ES Company Bank Account",
	"ES First Sales Invoice",
	"ES VAT Return Draft",
	"ES First Balance Sheet",
]


class TestWorkspace(IntegrationTestCase):
	def test_workspace_with_onboarding(self):
		workspace = frappe.get_doc("Workspace", "Spain")
		self.assertEqual(workspace.title, "España")
		blocks = json.loads(workspace.content)
		self.assertIn({"type": "onboarding", "name": "ES Onboarding"}, block_refs(blocks))

	def test_blocks_match_workspace_rows(self):
		"""Cada bloque del contenido tiene su fila (los bloques se unen por etiqueta)."""
		workspace = frappe.get_doc("Workspace", "Spain")
		available = {
			"card": {row.label for row in workspace.links if row.type == "Card Break"},
			"shortcut": {row.label for row in workspace.shortcuts},
			"number_card": {row.label for row in workspace.number_cards},
			"onboarding": {"ES Onboarding"},
		}
		for ref in block_refs(json.loads(workspace.content)):
			with self.subTest(block=ref):
				self.assertIn(ref["name"], available[ref["type"]])

	def test_links_point_to_existing_targets(self):
		workspace = frappe.get_doc("Workspace", "Spain")
		for link in workspace.links:
			if link.type != "Link":
				continue
			with self.subTest(link=link.label):
				self.assertTrue(frappe.db.exists(link.link_type, link.link_to))
		for shortcut in workspace.shortcuts:
			with self.subTest(shortcut=shortcut.label):
				self.assertTrue(frappe.db.exists(shortcut.type, shortcut.link_to))
		for card in workspace.number_cards:
			with self.subTest(number_card=card.label):
				self.assertTrue(frappe.db.exists("Number Card", card.number_card_name))

	def test_onboarding_steps_in_order(self):
		onboarding = frappe.get_doc("Module Onboarding", "ES Onboarding")
		self.assertEqual([row.step for row in onboarding.steps], EXPECTED_STEPS)

	def test_onboarding_targets_exist(self):
		for name in EXPECTED_STEPS:
			step = frappe.get_doc("Onboarding Step", name)
			with self.subTest(step=name):
				if step.reference_document:
					self.assertTrue(frappe.db.exists("DocType", step.reference_document))
				if step.reference_report:
					self.assertTrue(frappe.db.exists("Report", step.reference_report))
				if step.action == "Update Settings":
					self.assertTrue(frappe.get_meta(step.reference_document).has_field(step.field))

	def test_sidebar_links_exist(self):
		sidebar = frappe.get_doc("Sidebar", "Spain")
		self.assertEqual(sidebar.module, "ERPNext Spain")
		for item in sidebar.items:
			if item.type != "Link":
				continue
			with self.subTest(item=item.label):
				self.assertTrue(frappe.db.exists(item.link_type, item.link_to))

	def test_dock_mounted_on_erpnext(self):
		dock = frappe.get_doc("Dock", "erpnext_spain")
		self.assertEqual(dock.mount_on, "erpnext")
		self.assertEqual([(row.link_type, row.link_to) for row in dock.items], [("Sidebar", "Spain")])

	def test_every_module_folds_into_the_main_one(self):
		modules = set(frappe.get_module_list("erpnext_spain")) - {"ERPNext Spain"}
		folded = set(frappe.get_hooks("code_only_modules", app_name="erpnext_spain"))
		self.assertEqual(modules, folded)


def block_refs(blocks: list[dict]) -> list[dict]:
	keys = {
		"card": "card_name",
		"shortcut": "shortcut_name",
		"number_card": "number_card_name",
		"onboarding": "onboarding_name",
	}
	return [
		{"type": block["type"], "name": block["data"][keys[block["type"]]]}
		for block in blocks
		if block["type"] in keys
	]
