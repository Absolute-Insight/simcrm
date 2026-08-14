# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Rep-plan endpoint tests: ownership, upsert, and the propose-week gate."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.rep_plan import get_plan, propose_week, save_plan

REP = "plan-rep@crmtest.test"
OTHER = "plan-other@crmtest.test"


def make_sales_user(email: str, first_name: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


class RepPlanApiTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("CRM Rep Plan")
		frappe.db.delete("CRM Suggestion")
		make_sales_user(REP, "Plan Rep")
		make_sales_user(OTHER, "Plan Other")
		self.addCleanup(frappe.set_user, frappe.session.user)
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Plan API Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert().name
		today = frappe.utils.getdate()
		self.monday = str(frappe.utils.add_days(today, -today.weekday()))

	def tearDown(self):
		frappe.db.delete("CRM Rep Plan")
		frappe.db.delete("CRM Suggestion")
		super().tearDown()

	def make_suggestion(self, user):
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Suggestion",
					"signal": "idle_deal",
					"title": "Re-engage Plan API Org",
					"reference_doctype": "CRM Deal",
					"reference_docname": self.deal,
					"user": user,
					"status": "Open",
					"suggested_action": "schedule_call",
					"score": 70,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_save_and_get_round_trip_with_rollup(self):
		frappe.set_user(REP)
		out = save_plan(
			self.monday,
			[{"activity_type": "Call", "planned_date": self.monday, "note": "Call Acme"}],
		)
		self.assertEqual(len(out["items"]), 1)
		self.assertEqual(out["rollup"]["Call"], {"planned": 1, "done": 0, "missed": 0})

	def test_save_is_an_upsert_that_replaces_items(self):
		frappe.set_user(REP)
		save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		out = save_plan(
			self.monday,
			[
				{"activity_type": "Task", "planned_date": self.monday},
				{"activity_type": "Email", "planned_date": self.monday},
			],
		)
		self.assertEqual(len(out["items"]), 2)
		self.assertEqual(frappe.db.count("CRM Rep Plan", {"user": REP}), 1)

	def test_a_non_manager_cannot_read_another_users_plan(self):
		frappe.set_user(REP)
		save_plan(self.monday, [])
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			get_plan(self.monday, user=REP)

	def test_a_non_monday_week_start_is_rejected(self):
		frappe.set_user(REP)
		tuesday = str(frappe.utils.add_days(frappe.utils.getdate(self.monday), 1))
		with self.assertRaises(frappe.ValidationError):
			save_plan(tuesday, [])

	def test_propose_week_drafts_from_own_suggestions_and_writes_nothing(self):
		suggestion = self.make_suggestion(REP)
		self.make_suggestion(OTHER)  # someone else's — must not appear
		frappe.set_user(REP)
		drafts = propose_week(self.monday)
		self.assertEqual(len(drafts), 1)
		self.assertEqual(drafts[0]["activity_type"], "Call")
		self.assertEqual(drafts[0]["suggestion"], suggestion)
		self.assertEqual(frappe.db.count("CRM Rep Plan"), 0)
		self.assertEqual(frappe.db.get_value("CRM Suggestion", suggestion, "status"), "Open")

	def test_saving_a_proposed_plan_accepts_its_suggestions(self):
		suggestion = self.make_suggestion(REP)
		frappe.set_user(REP)
		drafts = propose_week(self.monday)
		save_plan(self.monday, drafts)
		self.assertEqual(frappe.db.get_value("CRM Suggestion", suggestion, "status"), "Accepted")

	def test_saving_preserves_matcher_fields_for_surviving_items(self):
		frappe.set_user(REP)
		out = save_plan(self.monday, [{"activity_type": "Task", "planned_date": self.monday, "note": "keep"}])
		item_name = out["items"][0]["name"]
		frappe.db.set_value("CRM Rep Plan Item", item_name, "status", "Done")
		out = save_plan(
			self.monday,
			[
				{"name": item_name, "activity_type": "Task", "planned_date": self.monday, "note": "keep"},
				{"activity_type": "Call", "planned_date": self.monday, "note": "new"},
			],
		)
		by_note = {i["note"]: i for i in out["items"]}
		self.assertEqual(by_note["keep"]["status"], "Done")
		self.assertEqual(by_note["new"]["status"], "Planned")
