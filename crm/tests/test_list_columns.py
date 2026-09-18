# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Hidden columns were dropped from the list view by removing them from the list
being iterated, which moves every later element down one and makes the loop skip
the next. A hidden column that happened to follow another hidden one was never
examined, so it stayed in the view — visible in a list, with its data fetched,
after an admin had hidden the field.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.doc import get_data

HIDDEN_FIELDS = ("website", "no_of_employees")


def column(key, label=None):
	return {"label": label or key.title(), "type": "Data", "key": key, "width": "10rem"}


class ListColumnVisibilityTest(IntegrationTestCase):
	def setUp(self):
		for fieldname in HIDDEN_FIELDS:
			frappe.make_property_setter(
				{
					"doctype": "CRM Lead",
					"fieldname": fieldname,
					"property": "hidden",
					"value": 1,
					"property_type": "Check",
				},
				is_system_generated=False,
			)
		frappe.clear_cache(doctype="CRM Lead")

	def tearDown(self):
		for fieldname in HIDDEN_FIELDS:
			frappe.db.delete(
				"Property Setter",
				{"doc_type": "CRM Lead", "field_name": fieldname, "property": "hidden"},
			)
		frappe.clear_cache(doctype="CRM Lead")

	def visible_keys(self, columns):
		result = get_data(
			doctype="CRM Lead",
			filters={},
			order_by="modified desc",
			page_length=1,
			columns=columns,
			rows=["name"],
			view={"view_type": "list"},
		)
		return [c.get("key") for c in result["columns"]]

	def test_two_adjacent_hidden_columns_are_both_dropped(self):
		"""The regression: the second of the pair used to survive."""
		keys = self.visible_keys(
			[column("name"), column("website"), column("no_of_employees"), column("modified")]
		)
		self.assertEqual(keys, ["name", "modified"])

	def test_a_lone_hidden_column_is_dropped(self):
		keys = self.visible_keys([column("name"), column("website"), column("modified")])
		self.assertEqual(keys, ["name", "modified"])

	def test_a_trailing_hidden_column_is_dropped(self):
		keys = self.visible_keys([column("name"), column("website")])
		self.assertEqual(keys, ["name"])

	def test_visible_columns_keep_their_order_and_are_untouched(self):
		keys = self.visible_keys([column("modified"), column("name")])
		self.assertEqual(keys, ["modified", "name"])


class DefaultColumnsSurviveHiddenTest(IntegrationTestCase):
	"""frappe's Contact keeps full_name hidden on the form; the contact list's
	own default columns name it first, and a list of contacts with no name column
	is what the hidden-field drop produced."""

	def test_the_contact_list_keeps_its_name_column(self):
		self.assertTrue(frappe.get_meta("Contact").get_field("full_name").hidden)
		result = get_data(
			doctype="Contact",
			filters={},
			order_by="modified desc",
			page_length=1,
			columns=[],
			rows=[],
			view={"view_type": "list"},
		)
		self.assertEqual(result["columns"][0].get("key"), "full_name")

	def test_a_hidden_field_outside_the_defaults_is_still_dropped(self):
		frappe.make_property_setter(
			{
				"doctype": "Contact",
				"fieldname": "designation",
				"property": "hidden",
				"value": 1,
				"property_type": "Check",
			},
			is_system_generated=False,
		)
		frappe.clear_cache(doctype="Contact")
		try:
			result = get_data(
				doctype="Contact",
				filters={},
				order_by="modified desc",
				page_length=1,
				columns=[column("full_name"), column("designation")],
				rows=["name"],
				view={"view_type": "list"},
			)
			self.assertEqual([c.get("key") for c in result["columns"]], ["full_name"])
		finally:
			frappe.db.delete(
				"Property Setter", {"doc_type": "Contact", "field_name": "designation", "property": "hidden"}
			)
			frappe.clear_cache(doctype="Contact")
