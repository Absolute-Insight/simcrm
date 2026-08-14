# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fulfilment matching tests.

``match_items`` is pure -- plan-item rows and actual-activity rows in,
assignments out -- so the matching rules live here without a site. The
scheduler entry is exercised against the test site at the end.
"""

from __future__ import annotations

from datetime import date, datetime

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.rep_planning import match_actuals, match_items

WEEK = date(2026, 8, 10)  # a Monday


def item(**overrides):
	row = {
		"name": "item-1",
		"activity_type": "Task",
		"planned_date": date(2026, 8, 12),
		"reference_doctype": "CRM Deal",
		"reference_docname": "DEAL-1",
		"status": "Planned",
	}
	row.update(overrides)
	return row


def actual(**overrides):
	row = {
		"doctype": "CRM Task",
		"name": "TASK-9",
		"kind": "Task",
		"reference_doctype": "CRM Deal",
		"reference_docname": "DEAL-1",
		"when": datetime(2026, 8, 12, 15, 0),
	}
	row.update(overrides)
	return row


class MatchItemsTest(UnitTestCase):
	def test_a_matching_actual_fulfils_the_item(self):
		out = match_items([item()], [actual()])
		self.assertEqual(out["item-1"]["name"], "TASK-9")

	def test_kind_mismatch_never_matches(self):
		out = match_items([item()], [actual(kind="Call")])
		self.assertEqual(out, {})

	def test_reference_mismatch_never_matches_when_the_item_names_one(self):
		out = match_items([item()], [actual(reference_docname="DEAL-2")])
		self.assertEqual(out, {})

	def test_an_unreferenced_item_matches_by_kind_within_the_week(self):
		out = match_items(
			[item(reference_doctype=None, reference_docname=None)],
			[actual(reference_docname="DEAL-2")],
		)
		self.assertEqual(out["item-1"]["name"], "TASK-9")

	def test_an_actual_outside_the_week_does_not_match(self):
		out = match_items([item()], [actual(when=datetime(2026, 8, 17, 9, 0))])
		self.assertEqual(out, {})

	def test_one_actual_fulfils_at_most_one_item_closest_date_wins(self):
		items = [
			item(name="far", planned_date=date(2026, 8, 10)),
			item(name="near", planned_date=date(2026, 8, 12)),
		]
		out = match_items(items, [actual()])
		self.assertEqual(list(out), ["near"])

	def test_two_actuals_fulfil_two_items(self):
		items = [
			item(name="a", planned_date=date(2026, 8, 10)),
			item(name="b", planned_date=date(2026, 8, 12)),
		]
		actuals = [
			actual(name="TASK-1", when=datetime(2026, 8, 10, 9, 0)),
			actual(name="TASK-2", when=datetime(2026, 8, 12, 9, 0)),
		]
		out = match_items(items, actuals)
		self.assertEqual({out["a"]["name"], out["b"]["name"]}, {"TASK-1", "TASK-2"})

	def test_done_items_are_not_rematched(self):
		out = match_items([item(status="Done")], [actual()])
		self.assertEqual(out, {})


class MatchActualsJobTest(IntegrationTestCase):
	USER = "rep-planner@crmtest.test"

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", self.USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": self.USER,
					"first_name": "Rep Planner",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		frappe.db.delete("CRM Rep Plan")
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Plan Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert().name

	def tearDown(self):
		frappe.db.delete("CRM Rep Plan")
		super().tearDown()

	def this_monday(self):
		today = frappe.utils.getdate()
		return frappe.utils.add_days(today, -today.weekday())

	def test_a_done_task_fulfils_the_planned_item_and_stale_items_go_missed(self):
		monday = self.this_monday()
		today = frappe.utils.getdate()
		plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": self.USER,
				"week_start": monday,
				"items": [
					{
						"activity_type": "Task",
						"planned_date": today,
						"reference_doctype": "CRM Deal",
						"reference_docname": self.deal,
					}
				],
			}
		).insert(ignore_permissions=True)

		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Planned touch",
				"status": "Done",
				"assigned_to": self.USER,
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal,
			}
		).insert(ignore_permissions=True)

		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")
		# autoincrement task names are ints; the Dynamic Link stores the string
		self.assertEqual(plan.items[0].fulfilled_by, str(task.name))

		# a week-old plan with an unfulfilled item goes Missed
		old_monday = frappe.utils.add_days(monday, -14)
		old_plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": self.USER,
				"week_start": old_monday,
				"items": [{"activity_type": "Call", "planned_date": old_monday}],
			}
		).insert(ignore_permissions=True)
		match_actuals()
		old_plan.reload()
		self.assertEqual(old_plan.items[0].status, "Missed")
