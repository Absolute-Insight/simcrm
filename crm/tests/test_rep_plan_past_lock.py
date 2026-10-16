# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""FCRM Settings -> "Plan only for today or later".

MBP's managers asked that a plan be a future event: nothing planned, moved or
removed before today, and unplanned work logged on the day. What a past item
became can still be said afterwards. The past cases all use *last* week, so
every day in them has passed whatever weekday the suite runs on.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.rep_plan import cancel_item, complete_item, get_plan, log_unplanned_visit, save_plan
from crm.tests.test_rep_plan_outcomes import make_sales_user, this_monday

REP = "past-lock-rep@crmtest.test"


def last_monday() -> str:
	return str(frappe.utils.getdate(this_monday()) - timedelta(days=7))


def day_of(monday: str, offset: int) -> str:
	return str(frappe.utils.getdate(monday) + timedelta(days=offset))


class PastDaysLockedTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		make_sales_user(REP, "Past Lock Rep")
		frappe.db.delete("CRM Rep Plan", {"user": REP})
		frappe.db.set_single_value("FCRM Settings", "lock_past_plans", 1)
		self.addCleanup(frappe.set_user, "Administrator")
		self.monday = last_monday()
		# what the importer or a save before the lock left behind
		self.plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": REP,
				"week_start": self.monday,
				"items": [
					{
						"activity_type": "Call",
						"planned_date": day_of(self.monday, 1),
						"note": "Ring the plant",
					},
					{"activity_type": "Call", "planned_date": day_of(self.monday, 2), "note": "Follow up"},
				],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(REP)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def rows(self) -> list[dict]:
		return [
			{key: row[key] for key in ("name", "activity_type", "planned_date", "note")}
			for row in get_plan(self.monday)["items"]
		]

	def test_nothing_new_is_planned_on_a_day_that_has_passed(self):
		with self.assertRaises(frappe.ValidationError):
			save_plan(
				self.monday,
				[*self.rows(), {"activity_type": "Visit", "planned_date": day_of(self.monday, 3)}],
			)

	def test_a_past_activity_is_not_moved_to_another_past_day(self):
		rows = self.rows()
		rows[0]["planned_date"] = day_of(self.monday, 0)
		with self.assertRaises(frappe.ValidationError):
			save_plan(self.monday, rows)

	def test_a_past_activity_is_cancelled_not_removed(self):
		with self.assertRaises(frappe.ValidationError):
			save_plan(self.monday, self.rows()[1:])

	def test_resending_the_past_unchanged_still_saves(self):
		saved = save_plan(self.monday, self.rows())
		self.assertEqual([row["note"] for row in saved["items"]], ["Ring the plant", "Follow up"])

	def test_a_past_activity_is_not_edited_or_moved_forward(self):
		today = str(frappe.utils.getdate())
		for field, changed in (("activity_type", "Visit"), ("note", "Went well"), ("planned_date", today)):
			with self.subTest(field=field):
				rows = self.rows()
				rows[0][field] = changed
				with self.assertRaises(frappe.ValidationError):
					save_plan(self.monday, rows)

	def test_today_and_later_are_open(self):
		today = str(frappe.utils.getdate())
		saved = save_plan(this_monday(), [{"activity_type": "Visit", "planned_date": today}])
		self.assertEqual(len(saved["items"]), 1)

	def test_the_outcome_of_a_past_activity_is_still_logged_and_cancelled(self):
		first, second = (row["name"] for row in self.rows())
		self.assertEqual(
			{row["name"]: row["status"] for row in complete_item(first, "Spoke to the foreman")["items"]}[
				first
			],
			"Done",
		)
		self.assertEqual(
			{row["name"]: row["status"] for row in cancel_item(second, "Plant shut")["items"]}[second],
			"Cancelled",
		)

	def test_unplanned_work_is_logged_on_the_day_not_after(self):
		yesterday = frappe.utils.getdate() - timedelta(days=1)
		with self.assertRaises(frappe.ValidationError):
			log_unplanned_visit(
				note="Called about the pump",
				when=str(datetime.combine(yesterday, time(10, 0))),
				activity_type="Call",
			)
		logged = log_unplanned_visit(note="Called about the pump", activity_type="Call")
		self.assertEqual([row["activity_type"] for row in logged["items"]][-1], "Call")

	def test_with_the_setting_off_the_past_is_open(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("FCRM Settings", "lock_past_plans", 0)
		frappe.set_user(REP)
		saved = save_plan(
			self.monday, [*self.rows(), {"activity_type": "Call", "planned_date": day_of(self.monday, 3)}]
		)
		self.assertEqual(len(saved["items"]), 3)
