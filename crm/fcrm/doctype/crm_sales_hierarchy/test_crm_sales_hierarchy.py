# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Tests for the tree that defines rep isolation.

This doctype decides which deals a manager can see, so a broken node here is a
permission bug rather than a display one — and until now it had no tests at all.
The two properties worth holding: a manager with reports cannot be deleted out
from under them, and the lft/rgt bounds every subtree query reads stay correct
after a delete.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.nestedset import NestedSetChildExistsError

MANAGER = "hierarchy-manager@crmtest.test"
REP = "hierarchy-rep@crmtest.test"


class TestCRMSalesHierarchy(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		for email, name, role in (
			(MANAGER, "Hierarchy Manager", "Sales Manager"),
			(REP, "Hierarchy Rep", "Sales User"),
		):
			if not frappe.db.exists("User", email):
				user = frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
				).insert(ignore_permissions=True)
				user.add_roles(role)
		self.clear_nodes()

	def tearDown(self):
		frappe.set_user("Administrator")
		self.clear_nodes()
		super().tearDown()

	def clear_nodes(self):
		# children first: the guard under test refuses to delete a parent
		for filters in ({"user": REP}, {"user": MANAGER}):
			for name in frappe.get_all("CRM Sales Hierarchy", filters=filters, pluck="name"):
				frappe.delete_doc("CRM Sales Hierarchy", name, force=True, ignore_permissions=True)

	def make_node(self, user: str, full_name: str, reports_to: str | None = None) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Sales Hierarchy",
					"user": user,
					"full_name": full_name,
					"reports_to": reports_to,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_a_manager_with_reports_cannot_be_deleted(self):
		"""on_trash overrode NestedSet's without calling super, which skipped
		validate_if_child_exists — so the delete went through and left the rep
		orphaned in the tree that decides what they can see."""
		manager = self.make_node(MANAGER, "Hierarchy Manager")
		self.make_node(REP, "Hierarchy Rep", reports_to=manager)

		with self.assertRaises(NestedSetChildExistsError):
			frappe.delete_doc("CRM Sales Hierarchy", manager, ignore_permissions=True)

		self.assertTrue(frappe.db.exists("CRM Sales Hierarchy", manager))

	def test_deleting_a_report_repairs_the_tree_bounds(self):
		"""update_nsm() is the other half super() was skipping. Every subtree
		query reads lft/rgt, so bounds left stale by a delete decide the wrong
		set of deals."""
		manager = self.make_node(MANAGER, "Hierarchy Manager")
		rep = self.make_node(REP, "Hierarchy Rep", reports_to=manager)

		frappe.delete_doc("CRM Sales Hierarchy", rep, ignore_permissions=True)

		lft, rgt = frappe.db.get_value("CRM Sales Hierarchy", manager, ["lft", "rgt"])
		self.assertEqual(rgt - lft, 1, "a manager with no reports left must be a leaf")

	def test_offboarding_a_manager_with_reports_leaves_their_roles_alone(self):
		"""The delete used to happen after the stripped roles were saved, so the
		failure landed on an admin who now had a half-offboarded user."""
		from crm.api.user import remove_crm_roles_from_user

		manager = self.make_node(MANAGER, "Hierarchy Manager")
		self.make_node(REP, "Hierarchy Rep", reports_to=manager)

		with self.assertRaises(frappe.ValidationError):
			remove_crm_roles_from_user(MANAGER)

		self.assertIn("Sales Manager", frappe.get_roles(MANAGER))
		self.assertTrue(frappe.db.exists("CRM Sales Hierarchy", manager))
