# Workspace "España" y onboarding (spec 01 §6).

import json

import frappe
from frappe.tests import IntegrationTestCase

EXPECTED_STEPS = [
	"ES Company Tax Data",
	"ES Apply PGC Chart",
	"ES Review Tax Templates",
	"ES Invoice Series",
	"ES First Balance Sheet",
]


class TestWorkspace(IntegrationTestCase):
	def test_workspace_with_onboarding(self):
		workspace = frappe.get_doc("Workspace", "Spain")
		self.assertEqual(workspace.title, "España")
		self.assertEqual(workspace.module_onboarding, "ES Onboarding")
		blocks = json.loads(workspace.content)
		self.assertIn("onboarding", {block["type"] for block in blocks})

	def test_onboarding_steps_in_order(self):
		onboarding = frappe.get_doc("Module Onboarding", "ES Onboarding")
		self.assertEqual([row.step for row in onboarding.steps], EXPECTED_STEPS)

	def test_links_point_to_existing_targets(self):
		workspace = frappe.get_doc("Workspace", "Spain")
		for link in workspace.links:
			if link.type != "Link":
				continue
			with self.subTest(link=link.label):
				self.assertTrue(frappe.db.exists(link.link_type, link.link_to))
