# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""CRM Forecast Snapshot rows follow the sales hierarchy like every other aggregate.

Each row is a monthly revenue forecast and the actual closed at snapshot time --
per rep, per team node and for the whole site. The dashboard picks one series
server-side, but the doctype itself carried only a Sales Manager role grant, so
an in-tree manager could ``get_list`` the company total and every other team's
numbers. These tests knock on that generic door.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

MANAGER = "snapshot-manager@crmtest.test"
MY_REP = "snapshot-my-rep@crmtest.test"
OTHER_REP = "snapshot-other-rep@crmtest.test"


def ensure_user(email: str, *roles: str) -> None:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	frappe.get_doc("User", email).add_roles(*roles)


class ForecastSnapshotPermissionTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(MANAGER, "Sales Manager", "Sales User")
		ensure_user(MY_REP, "Sales User")
		ensure_user(OTHER_REP, "Sales User")
		self.saved_hierarchy_flag = frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", [MANAGER, MY_REP, OTHER_REP])})
		node = frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": MANAGER}).insert(
			ignore_permissions=True
		)
		frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": MY_REP, "reports_to": node.name}).insert(
			ignore_permissions=True
		)
		frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": OTHER_REP}).insert(ignore_permissions=True)
		frappe.clear_cache()

		self.rows = {}
		for scope, user in (("Site", ""), ("Team", MANAGER), ("Rep", MY_REP), ("Rep", OTHER_REP)):
			self.rows[(scope, user)] = frappe.get_doc(
				{
					"doctype": "CRM Forecast Snapshot",
					"snapshot_date": "2026-01-04",
					"month": "2026-01",
					"scope": scope,
					"user": user,
					"forecasted": 1000,
					"actual_at_snapshot": 500,
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		for row in self.rows.values():
			frappe.delete_doc("CRM Forecast Snapshot", row.name, force=True, ignore_permissions=True)
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", [MANAGER, MY_REP, OTHER_REP])})
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", self.saved_hierarchy_flag or 0)
		frappe.clear_cache()
		super().tearDown()

	def test_an_in_tree_manager_lists_only_their_subtree_and_their_own_team_row(self):
		frappe.set_user(MANAGER)
		visible = {
			(r.scope, r.user or "")
			for r in frappe.get_list(
				"CRM Forecast Snapshot", filters={"month": "2026-01"}, fields=["scope", "user"], limit=0
			)
		}
		self.assertIn(("Rep", MY_REP), visible)
		self.assertIn(("Team", MANAGER), visible)
		self.assertNotIn(("Rep", OTHER_REP), visible)
		self.assertNotIn(("Site", ""), visible)

	def test_the_record_door_agrees_with_the_list_door(self):
		frappe.set_user(MANAGER)
		self.assertTrue(
			frappe.has_permission("CRM Forecast Snapshot", "read", self.rows[("Rep", MY_REP)].name)
		)
		self.assertTrue(
			frappe.has_permission("CRM Forecast Snapshot", "read", self.rows[("Team", MANAGER)].name)
		)
		self.assertFalse(
			frappe.has_permission("CRM Forecast Snapshot", "read", self.rows[("Rep", OTHER_REP)].name)
		)
		self.assertFalse(frappe.has_permission("CRM Forecast Snapshot", "read", self.rows[("Site", "")].name))

	def test_a_rep_has_no_grant_at_all(self):
		frappe.set_user(MY_REP)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("CRM Forecast Snapshot", fields=["scope"])
