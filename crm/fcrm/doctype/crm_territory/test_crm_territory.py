# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import json
import os

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

DOCTYPE_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crm_territory.json")


def load_meta() -> dict:
	with open(DOCTYPE_JSON) as f:
		return json.load(f)


class TestCRMTerritory(UnitTestCase):
	"""The doctype used to declare itself a tree with a manager, a parent link and
	the nested-set bookkeeping columns. The controller is a plain ``Document``, not
	``NestedSet``, so no code maintained any of it and no code read any of it --
	but the desk showed a tree view, and an admin who nested provinces into regions
	got a hierarchy that rolled up nowhere. A territory is a flat name."""

	def test_the_doctype_does_not_claim_to_be_a_tree(self):
		meta = load_meta()
		self.assertNotIn("is_tree", meta)
		self.assertNotIn("nsm_parent_field", meta)

	def test_the_dead_fields_are_gone(self):
		from crm.patches.v1_0.drop_crm_territory_tree_fields import DEAD_COLUMNS

		fieldnames = {field["fieldname"] for field in load_meta()["fields"]}
		self.assertEqual(fieldnames, {"territory_name"})
		# The patch cleans up exactly the columns the JSON stopped declaring.
		self.assertFalse(fieldnames & set(DEAD_COLUMNS))


class TerritorySeedingTest(IntegrationTestCase):
	def test_the_provinces_still_seed(self):
		"""``ensure_sa_provinces`` runs on every install and from its own patch;
		the lead and organization forms pick a province out of this table."""
		from crm.install import SA_PROVINCES, ensure_sa_provinces

		ensure_sa_provinces()
		for province in SA_PROVINCES:
			self.assertTrue(frappe.db.exists("CRM Territory", province), province)
