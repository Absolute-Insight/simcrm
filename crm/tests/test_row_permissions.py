# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Row-level access on the doctypes the new surfaces write to.

The API endpoints scope every read and write by user, but they are not the only
door: ``frappe.client.get_list`` / ``get_doc`` / ``set_value`` reach these
doctypes directly from the browser with the session user's rights. These tests
knock on that second door, so a future permission-block edit that opens it up
fails here rather than in production.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

ALICE = "rowperm-alice@crmtest.test"
BOB = "rowperm-bob@crmtest.test"


def ensure_rep(email: str, name: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


class RowPermissionTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_rep(ALICE, "Alice")
		ensure_rep(BOB, "Bob")
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Suggestion", {"user": ("in", [ALICE, BOB])})
		frappe.db.delete("CRM Rep Plan", {"user": ("in", [ALICE, BOB])})

		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Row Perm Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.org, "deal_owner": BOB}
		).insert(ignore_permissions=True)

		self.bobs_suggestion = frappe.get_doc(
			{
				"doctype": "CRM Suggestion",
				"signal": "idle_deal",
				"title": "Bob should call this deal",
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal.name,
				"user": BOB,
				"suggested_action": "create_task",
				"status": "Open",
			}
		).insert(ignore_permissions=True)

		monday = frappe.utils.getdate()
		monday = frappe.utils.add_days(monday, -monday.weekday())
		self.bobs_plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": BOB,
				"week_start": monday,
				"items": [{"activity_type": "Call", "planned_date": monday, "note": "Bob's call"}],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Suggestion", {"user": ("in", [ALICE, BOB])})
		frappe.db.delete("CRM Rep Plan", {"user": ("in", [ALICE, BOB])})
		frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)
		super().tearDown()

	# --- suggestions ----------------------------------------------------

	def test_a_rep_cannot_list_another_reps_suggestions(self):
		frappe.set_user(ALICE)
		names = frappe.get_list("CRM Suggestion", pluck="name")
		self.assertNotIn(self.bobs_suggestion.name, names)

	def test_a_rep_cannot_open_another_reps_suggestion(self):
		frappe.set_user(ALICE)
		self.assertFalse(frappe.has_permission("CRM Suggestion", doc=self.bobs_suggestion.name, ptype="read"))

	def test_a_rep_cannot_flip_another_reps_suggestion_directly(self):
		frappe.set_user(ALICE)
		self.assertFalse(
			frappe.has_permission("CRM Suggestion", doc=self.bobs_suggestion.name, ptype="write")
		)

	def test_a_manager_still_sees_the_whole_queue(self):
		frappe.set_user("Administrator")
		names = frappe.get_list("CRM Suggestion", pluck="name")
		self.assertIn(self.bobs_suggestion.name, names)

	# --- rep plans ------------------------------------------------------

	def test_a_rep_cannot_list_another_reps_plan(self):
		frappe.set_user(ALICE)
		names = frappe.get_list("CRM Rep Plan", pluck="name")
		self.assertNotIn(str(self.bobs_plan.name), [str(n) for n in names])

	def test_a_rep_cannot_edit_another_reps_plan_directly(self):
		frappe.set_user(ALICE)
		self.assertFalse(frappe.has_permission("CRM Rep Plan", doc=self.bobs_plan.name, ptype="write"))

	def test_a_manager_may_read_a_plan_but_not_rewrite_it(self):
		"""Managers coach, they do not author someone else's week — the API says so and
		the doctype has to agree, or the API rule is decorative."""
		frappe.set_user("Administrator")
		self.assertTrue(frappe.has_permission("CRM Rep Plan", doc=self.bobs_plan.name, ptype="read"))

		manager = "rowperm-manager@crmtest.test"
		if not frappe.db.exists("User", manager):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": manager,
					"first_name": "Manager",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Sales Manager")
		frappe.set_user(manager)
		self.assertTrue(frappe.has_permission("CRM Rep Plan", doc=self.bobs_plan.name, ptype="read"))
		self.assertFalse(frappe.has_permission("CRM Rep Plan", doc=self.bobs_plan.name, ptype="write"))

	def test_a_rep_still_owns_their_own_plan(self):
		frappe.set_user(BOB)
		self.assertTrue(frappe.has_permission("CRM Rep Plan", doc=self.bobs_plan.name, ptype="write"))
		self.assertIn(
			str(self.bobs_plan.name), [str(n) for n in frappe.get_list("CRM Rep Plan", pluck="name")]
		)

	# --- assignees ------------------------------------------------------

	def test_a_rep_cannot_enumerate_assignees_of_a_deal_they_cannot_read(self):
		"""get_assigned_users reads ToDo through frappe.get_all, which does not
		check permissions, and ToDo carries no CRM permission condition. Named
		over HTTP that let anyone walk the org chart one record at a time:
		point at a deal, learn who works it."""
		from crm.api.doc import get_assigned_users

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(ALICE)
		with self.assertRaises(frappe.PermissionError):
			get_assigned_users("CRM Deal", self.deal.name)

	def test_the_owner_still_reads_their_own_deals_assignees(self):
		from crm.api.doc import get_assigned_users

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(BOB)
		self.assertIsInstance(get_assigned_users("CRM Deal", self.deal.name), list)
