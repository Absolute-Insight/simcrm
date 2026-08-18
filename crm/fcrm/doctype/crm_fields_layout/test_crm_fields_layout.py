# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for the doctype behind the field layout API.

This file was the `bench new-doctype` scaffold — `class …(UnitTestCase): pass` —
counted by discovery and asserting nothing, on a module that decides two things
worth holding:

`handle_perm_level_restrictions` is the reason a permlevel'd field does not
reach the browser. Frappe enforces permlevels on write, but the *layout* is what
decides whether the field is rendered at all, and a regression here leaks a
restricted field into the form rather than raising anything. Its three branches
are one `if` apart and none of them was covered.

`save_fields_layout` is whitelisted, so it is reachable by any logged-in user;
the only thing between a Sales User and the layout every rep sees is one
`has_permission` call.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_fields_layout import crm_fields_layout as L

MODULE = "crm.fcrm.doctype.crm_fields_layout.crm_fields_layout"
REP = "layout-rep@crmtest.test"


class TestPermLevelRestrictions(IntegrationTestCase):
	"""The three branches of handle_perm_level_restrictions.

	Driven through a patched `get_permlevel_access` rather than a real
	permlevel'd DocType: the branch logic is what this protects, and building a
	custom DocType per case would test Frappe's permission engine instead.
	"""

	def apply(self, permlevel, write_levels, read_levels):
		field = frappe._dict({"fieldname": "secret", "permlevel": permlevel})
		levels = {"write": write_levels, "read": read_levels}
		with patch(f"{MODULE}.get_permlevel_access", side_effect=lambda t, *a, **k: levels[t]):
			L.handle_perm_level_restrictions(field, "CRM Lead")
		return field

	def test_permlevel_zero_is_left_alone(self):
		field = self.apply(0, write_levels=[], read_levels=[])
		self.assertIsNone(field.get("hidden"))
		self.assertIsNone(field.get("read_only"))

	def test_read_without_write_becomes_read_only(self):
		field = self.apply(1, write_levels=[0], read_levels=[0, 1])
		self.assertEqual(field.read_only, 1)
		self.assertIsNone(field.get("hidden"))

	def test_neither_read_nor_write_is_hidden(self):
		field = self.apply(1, write_levels=[0], read_levels=[0])
		self.assertEqual(field.hidden, 1)

	def test_full_access_leaves_the_field_editable(self):
		"""The control. Without this, "hidden" could be unconditional."""
		field = self.apply(1, write_levels=[0, 1], read_levels=[0, 1])
		self.assertIsNone(field.get("hidden"))
		self.assertIsNone(field.get("read_only"))


class TestSaveFieldsLayout(IntegrationTestCase):
	LAYOUT_DT = "CRM Lead"
	LAYOUT_TYPE = "Side Panel"

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.previous = frappe.db.get_value(
			"CRM Fields Layout", {"dt": self.LAYOUT_DT, "type": self.LAYOUT_TYPE}, "layout"
		)
		if not frappe.db.exists("User", REP):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": REP,
					"first_name": "Layout Rep",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")

	def tearDown(self):
		frappe.set_user("Administrator")
		if self.previous is not None:
			doc = frappe.get_doc("CRM Fields Layout", {"dt": self.LAYOUT_DT, "type": self.LAYOUT_TYPE})
			doc.layout = self.previous
			doc.save(ignore_permissions=True)
		super().tearDown()

	def test_a_sales_user_may_not_rewrite_the_layout(self):
		"""The property, whichever layer enforces it.

		Deleting the explicit `has_permission` call does not make this fail --
		`doc.save()` refuses too. Kept anyway, because the property is what
		matters and the endpoint is whitelisted; the test below is the one that
		pins the explicit gate.
		"""
		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			L.save_fields_layout(self.LAYOUT_DT, self.LAYOUT_TYPE, json.dumps([]))

	def test_the_refusal_comes_from_this_endpoint_not_from_the_save(self):
		"""Refusing up front is the difference between "not permitted to modify
		fields layout" and whatever `doc.save()` happens to say three frames
		deeper -- and it refuses before building a document at all."""
		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError) as caught:
			L.save_fields_layout(self.LAYOUT_DT, self.LAYOUT_TYPE, json.dumps([]))
		self.assertIn("fields layout", str(caught.exception).lower())

	def test_the_refused_save_changes_nothing(self):
		frappe.set_user(REP)
		try:
			L.save_fields_layout(self.LAYOUT_DT, self.LAYOUT_TYPE, json.dumps([{"label": "Injected"}]))
		except frappe.PermissionError:
			pass
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value(
				"CRM Fields Layout", {"dt": self.LAYOUT_DT, "type": self.LAYOUT_TYPE}, "layout"
			),
			self.previous,
		)

	def test_an_administrator_round_trips_the_layout(self):
		"""The control: the permission check must not refuse everyone."""
		layout = json.dumps([{"label": "Round Trip", "name": "rt", "columns": []}])
		saved = L.save_fields_layout(self.LAYOUT_DT, self.LAYOUT_TYPE, layout)
		self.assertEqual(json.loads(saved), json.loads(layout))
		self.assertEqual(
			json.loads(
				frappe.db.get_value(
					"CRM Fields Layout", {"dt": self.LAYOUT_DT, "type": self.LAYOUT_TYPE}, "layout"
				)
			),
			json.loads(layout),
		)


class TestGetFieldsLayout(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_a_doctype_with_no_layout_still_gets_tabs(self):
		"""Callers index into tabs[].sections[]; an empty list would break them."""
		tabs = L.get_fields_layout("CRM Lead Status", "Quick Entry")
		self.assertIsInstance(tabs, list)
		self.assertTrue(tabs)
		self.assertIn("sections", tabs[0])

	def test_a_flat_section_list_is_wrapped_in_a_tab(self):
		"""Older layouts are stored as a bare list of sections, not tabs."""
		name = frappe.db.get_value("CRM Fields Layout", {"dt": "CRM Lead", "type": "Side Panel"})
		self.assertIsNotNone(name, "expected the shipped Lead side-panel layout")
		doc = frappe.get_doc("CRM Fields Layout", name)
		previous = doc.layout
		doc.layout = json.dumps([{"label": "Flat", "name": "flat", "columns": []}])
		doc.save(ignore_permissions=True)
		try:
			tabs = L.get_fields_layout("CRM Lead", "Side Panel")
			self.assertEqual(len(tabs), 1)
			self.assertEqual(tabs[0]["name"], "first_tab")
			self.assertEqual(tabs[0]["sections"][0]["label"], "Flat")
		finally:
			doc.layout = previous
			doc.save(ignore_permissions=True)
