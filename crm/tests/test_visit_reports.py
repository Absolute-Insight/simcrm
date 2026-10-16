# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Visit targets, the visit and activity reports, customer interaction, and how
plan adherence treats a cancelled plan item.

Everything is dated in *last* week, Monday to Sunday, so every day in it has
settled whatever weekday the suite runs on -- today is never counted against
anyone, and a fixture dated today would make the expected numbers depend on the
clock. Each test rolls back, and every aggregate is read for a named rep or as
a manager whose subtree holds only this suite's users, so demo data on the site
cannot reach an assertion.
"""

from __future__ import annotations

from datetime import datetime, time

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, nowdate

from crm.api import visit_targets as targets_api
from crm.api.dashboard import (
	activities_by_type,
	customer_interaction,
	plan_adherence,
	visits_by_rep,
)
from crm.api.reports import get_report
from crm.api.visit_targets import target_for, working_days

REP = "visits-rep@crmtest.test"
MANAGER = "visits-manager@crmtest.test"
OUTSIDER = "visits-outsider@crmtest.test"


def ensure_user(email: str, name: str, role: str = "Sales User") -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(role)


def last_week() -> tuple:
	today = getdate(nowdate())
	monday = add_days(today, -today.weekday() - 7)
	return getdate(monday), getdate(add_days(monday, 6))


def make_target(user: str, per_week: int) -> None:
	frappe.get_doc({"doctype": "CRM Visit Target", "user": user, "visits_per_week": per_week}).insert(
		ignore_permissions=True
	)


def make_plan(user: str, monday, items: list[dict]):
	return frappe.get_doc(
		{"doctype": "CRM Rep Plan", "user": user, "week_start": monday, "items": items}
	).insert(ignore_permissions=True)


def make_event(owner: str, day, organization: str | None = None, status: str = "Completed", **values):
	"""A calendar event as its rep: frappe stamps ``owner`` from the session."""
	previous = frappe.session.user
	frappe.set_user(owner)
	try:
		return frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Visit",
				"starts_on": datetime.combine(getdate(day), time(10, 0)),
				"event_type": "Private",
				"event_category": "Visit",
				"status": status,
				"event_participants": (
					[{"reference_doctype": "CRM Organization", "reference_docname": organization}]
					if organization
					else []
				),
				**values,
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.set_user(previous)


class VisitFixture:
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(REP, "Visits Rep")
		ensure_user(MANAGER, "Visits Manager", "Sales Manager")
		ensure_user(OUTSIDER, "Visits Outsider")
		frappe.db.delete("CRM Visit Target", {"user": ("in", [REP, MANAGER, OUTSIDER])})
		self.monday, self.sunday = last_week()
		self.start, self.end = str(self.monday), str(self.sunday)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.cache.delete_value("crm_sales_hierarchy_subtree")
		super().tearDown()

	def make_hierarchy(self):
		"""MANAGER over REP; OUTSIDER in no tree."""
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", [MANAGER, REP, OUTSIDER])})
		top = frappe.get_doc(
			{"doctype": "CRM Sales Hierarchy", "user": MANAGER, "full_name": "Visits Manager"}
		).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": REP, "reports_to": top.name}).insert(
			ignore_permissions=True
		)
		frappe.cache.delete_value("crm_sales_hierarchy_subtree")

	def day(self, offset: int):
		return add_days(self.monday, offset)


class TargetProrationTest(VisitFixture, IntegrationTestCase):
	def test_working_days_count_monday_to_friday_inclusive(self):
		self.assertEqual(working_days("2026-03-02", "2026-03-08"), 5)  # Mon..Sun
		self.assertEqual(working_days("2026-03-07", "2026-03-08"), 0)  # a weekend
		self.assertEqual(working_days("2026-03-01", "2026-03-31"), 22)
		self.assertEqual(working_days("2026-03-04", "2026-03-04"), 1)
		self.assertEqual(working_days("2026-03-05", "2026-03-04"), 0)  # inverted

	def test_a_week_is_the_weekly_target_and_a_month_its_working_days(self):
		make_target(REP, 15)
		self.assertEqual(target_for([REP], "2026-03-02", "2026-03-08"), {REP: 15})
		self.assertEqual(target_for([REP], "2026-03-01", "2026-03-31"), {REP: 66})  # 15 x 22 / 5
		self.assertAlmostEqual(target_for([REP], "2026-03-02", "2026-03-04")[REP], 9)

	def test_a_rep_without_a_target_is_left_out_not_zero(self):
		make_target(REP, 10)
		self.assertEqual(target_for([REP, OUTSIDER], "2026-03-02", "2026-03-08"), {REP: 10})
		self.assertEqual(target_for([], "2026-03-02", "2026-03-08"), {})


class VisitTargetPermissionTest(VisitFixture, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.make_hierarchy()

	def test_a_rep_cannot_set_a_target_not_even_their_own(self):
		frappe.set_user(REP)
		for whom in (REP, OUTSIDER):
			with self.subTest(user=whom), self.assertRaises(frappe.PermissionError):
				targets_api.set_visit_target(whom, 5)
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("CRM Visit Target", REP))

	def test_a_manager_cannot_set_a_target_outside_their_subtree(self):
		make_target(OUTSIDER, 7)
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			targets_api.set_visit_target(OUTSIDER, 20)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CRM Visit Target", OUTSIDER, "visits_per_week"), 7)

	def test_a_manager_cannot_set_their_own_target(self):
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			targets_api.set_visit_target(MANAGER, 3)
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("CRM Visit Target", MANAGER))

	def test_a_manager_sets_updates_and_clears_their_reps_target(self):
		frappe.set_user(MANAGER)
		self.assertEqual(targets_api.set_visit_target(REP, 12)["visits_per_week"], 12)
		self.assertEqual(targets_api.set_visit_target(REP, "15")["visits_per_week"], 15)
		self.assertEqual(frappe.db.get_value("CRM Visit Target", REP, "visits_per_week"), 15)
		targets_api.set_visit_target(REP, 0)
		self.assertFalse(frappe.db.exists("CRM Visit Target", REP))
		targets_api.set_visit_target(REP, 4)
		targets_api.set_visit_target(REP, "")
		self.assertFalse(frappe.db.exists("CRM Visit Target", REP))

	def test_a_target_is_a_whole_non_negative_number(self):
		frappe.set_user(MANAGER)
		for bad in (-1, "2.5", "abc"):
			with self.subTest(value=bad), self.assertRaises(frappe.ValidationError):
				targets_api.set_visit_target(REP, bad)
		self.assertFalse(frappe.db.exists("CRM Visit Target", REP))

	def test_an_administrator_sets_a_managers_target(self):
		self.assertEqual(targets_api.set_visit_target(MANAGER, 8)["visits_per_week"], 8)

	def test_the_grid_lists_the_subtree_and_says_which_rows_the_caller_may_change(self):
		make_target(REP, 9)
		make_target(OUTSIDER, 7)
		frappe.set_user(MANAGER)
		rows = {row["user"]: row for row in targets_api.get_visit_targets()}
		self.assertEqual(set(rows), {MANAGER, REP})
		self.assertEqual(rows[REP]["visits_per_week"], 9)
		self.assertTrue(rows[REP]["editable"])
		self.assertFalse(rows[MANAGER]["editable"])
		self.assertIsNone(rows[MANAGER]["visits_per_week"])

	def test_a_rep_reads_only_their_own_row_and_cannot_edit_it(self):
		make_target(REP, 9)
		frappe.set_user(REP)
		rows = targets_api.get_visit_targets()
		self.assertEqual([(r["user"], r["visits_per_week"], r["editable"]) for r in rows], [(REP, 9, False)])


class LockedRepTest(VisitFixture, IntegrationTestCase):
	"""A rep disabled before go-live is still a rep to plan and set targets for.

	MBP's reps were disabled so they could not log in yet while their imported
	history filled the planner; the enabled-only rep list emptied the managers'
	team week and Settings -> Visit Targets on production.
	"""

	def setUp(self):
		super().setUp()
		frappe.db.set_value("User", REP, "enabled", 0)
		make_plan(REP, self.monday, [{"activity_type": "Visit", "planned_date": self.day(1)}])

	def test_the_team_week_and_the_picker_keep_a_disabled_rep_with_recent_plans(self):
		from crm.api.rep_plan import get_team_week, get_visible_reps

		self.assertIn(REP, get_visible_reps())
		rows = {rep["user"]: rep for rep in get_team_week(self.start)["reps"]}
		self.assertEqual(len(rows[REP]["items"]), 1)
		self.assertEqual(rows[REP]["full_name"], "Visits Rep")

	def test_a_manager_sets_a_target_for_a_disabled_rep(self):
		self.assertIn(REP, {row["user"] for row in targets_api.get_visit_targets()})
		self.assertEqual(targets_api.set_visit_target(REP, 10)["visits_per_week"], 10)

	def test_a_rep_who_left_drops_out_once_their_plans_are_old(self):
		from crm.api.rep_plan import get_team_week, get_visible_reps, planning_reps
		from crm.rep_planning import MATCH_HORIZON_WEEKS

		old_monday = add_days(self.monday, -7 * (MATCH_HORIZON_WEEKS + 2))
		frappe.db.set_value("User", OUTSIDER, "enabled", 0)
		make_plan(OUTSIDER, old_monday, [{"activity_type": "Call", "planned_date": old_monday}])

		self.assertNotIn(OUTSIDER, planning_reps())
		self.assertNotIn(OUTSIDER, get_visible_reps())
		with self.assertRaises(frappe.ValidationError):
			targets_api.set_visit_target(OUTSIDER, 5)
		# the week they planned still shows them
		old_rows = {rep["user"] for rep in get_team_week(str(old_monday))["reps"]}
		self.assertIn(OUTSIDER, old_rows)


class VisitsByRepTest(VisitFixture, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		make_plan(
			REP,
			self.monday,
			[
				{"activity_type": "Visit", "planned_date": self.day(0), "status": "Done"},
				{"activity_type": "Visit", "planned_date": self.day(1), "status": "Done"},
				{"activity_type": "Visit", "planned_date": self.day(2), "status": "Done"},
				# logged after the fact, still a customer visit
				{"activity_type": "Unplanned Meeting", "planned_date": self.day(3), "status": "Done"},
				{
					"activity_type": "Visit",
					"planned_date": self.day(3),
					"status": "Cancelled",
					"manual_override": 1,
				},
				{"activity_type": "Visit", "planned_date": self.day(4), "status": "Missed"},
				# not a visit
				{"activity_type": "Call", "planned_date": self.day(1), "status": "Done"},
				{"activity_type": "Delivery", "planned_date": self.day(2), "status": "Done"},
			],
		)

	def row(self, **kwargs):
		rows = visits_by_rep(self.start, self.end, REP, **kwargs)
		self.assertEqual([r["user"] for r in rows], [REP])
		return rows[0]

	def test_counts_split_by_status_and_only_visits_count(self):
		make_target(REP, 5)
		row = self.row()
		self.assertEqual(
			(row["scheduled"], row["completed"], row["cancelled"], row["missed"], row["open"]),
			(6, 4, 1, 1, 0),
		)
		self.assertEqual((row["target"], row["target_to_date"]), (5, 5))
		self.assertEqual(row["attainment"], 80)
		self.assertEqual(row["on_track"], "Behind")

	def test_meeting_the_target_due_so_far_is_on_track(self):
		make_target(REP, 4)
		row = self.row()
		self.assertEqual((row["attainment"], row["on_track"]), (100, "On track"))

	def test_no_target_is_not_behind_or_zero_percent(self):
		row = self.row()
		self.assertIsNone(row["target"])
		self.assertIsNone(row["attainment"])
		self.assertEqual(row["on_track"], "No target")

	def test_only_the_settled_part_of_the_period_is_due(self):
		"""Last week plus this week: the whole target is two weeks, but what is due
		stops at yesterday -- today has not settled."""
		make_target(REP, 5)
		this_sunday = add_days(self.monday, 13)
		rows = visits_by_rep(self.start, str(this_sunday), REP)
		yesterday = add_days(nowdate(), -1)
		self.assertEqual(rows[0]["target"], 10)
		self.assertEqual(rows[0]["target_to_date"], round(5 * working_days(self.monday, yesterday) / 5, 1))

	def test_a_rep_with_a_target_and_no_visits_still_has_a_row(self):
		make_target(OUTSIDER, 3)
		rows = visits_by_rep(self.start, self.end, OUTSIDER)
		self.assertEqual(len(rows), 1)
		self.assertEqual((rows[0]["completed"], rows[0]["target"], rows[0]["on_track"]), (0, 3, "Behind"))

	def test_a_manager_reads_their_subtree_only(self):
		self.make_hierarchy()
		make_target(REP, 5)
		make_target(OUTSIDER, 5)
		frappe.set_user(MANAGER)
		self.assertEqual({r["user"] for r in visits_by_rep(self.start, self.end)}, {REP})

	def test_the_report_is_the_aggregate_with_the_reps_name(self):
		make_target(REP, 5)
		report = get_report("visits_by_rep", self.start, self.end, REP)
		self.assertEqual(report["rows"][0]["rep"], "Visits Rep")
		self.assertEqual(report["rows"][0]["completed"], self.row()["completed"])
		self.assertFalse(
			get_report("visits_by_rep", self.start, self.end, REP, "Gauteng")["territory_filtered"]
		)

	def test_activities_by_type_counts_every_type(self):
		rows = {r["activity_type"]: r for r in activities_by_type(self.start, self.end, REP)}
		self.assertEqual(list(rows), ["Visit", "Unplanned Meeting", "Delivery", "Call"])  # planner order
		self.assertEqual(
			(rows["Visit"]["scheduled"], rows["Visit"]["done"], rows["Visit"]["cancelled"]), (5, 3, 1)
		)
		self.assertEqual(rows["Visit"]["missed"], 1)
		self.assertEqual((rows["Call"]["scheduled"], rows["Call"]["done"]), (1, 1))


class CustomerInteractionTest(VisitFixture, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.orgs = {}
		for key in ("visited", "untouched", "called", "history"):
			self.orgs[key] = (
				frappe.get_doc(
					{"doctype": "CRM Organization", "organization_name": f"Interaction {key.title()} Pty"}
				)
				.insert(ignore_permissions=True)
				.name
			)

	def rows(self, **kwargs):
		return {r["organization"]: r for r in customer_interaction(self.start, self.end, REP, **kwargs)}

	def test_a_visit_completed_from_the_plan_is_counted_once(self):
		"""Completing a planned visit writes a Visit event as the item's
		``fulfilled_by``; the item and the event are one visit."""
		event = make_event(REP, self.day(1), self.orgs["visited"])
		make_plan(
			REP,
			self.monday,
			[
				{
					"activity_type": "Visit",
					"planned_date": self.day(1),
					"status": "Done",
					"manual_override": 1,
					"organization": self.orgs["visited"],
					"fulfilled_by_doctype": "Event",
					"fulfilled_by": event.name,
				}
			],
		)
		row = self.rows()[self.orgs["visited"]]
		self.assertEqual((row["visits"], row["total"]), (1, 1))
		self.assertEqual(row["last_interaction"], str(self.day(1)))
		self.assertEqual(row["last_rep"], "Visits Rep")
		self.assertEqual(row["days_since"], 5)  # Tuesday to Sunday

	def test_a_calendar_visit_and_a_call_both_count(self):
		make_event(REP, self.day(2), self.orgs["called"])
		make_plan(
			REP,
			self.monday,
			[
				{
					"activity_type": "Call",
					"planned_date": self.day(3),
					"status": "Done",
					"organization": self.orgs["called"],
				},
				# not done, so not an interaction
				{
					"activity_type": "Email",
					"planned_date": self.day(3),
					"status": "Missed",
					"organization": self.orgs["called"],
				},
			],
		)
		row = self.rows()[self.orgs["called"]]
		self.assertEqual((row["visits"], row["calls"], row["emails"], row["total"]), (1, 1, 0, 2))
		self.assertEqual(row["last_interaction"], str(self.day(3)))

	def test_an_event_recording_an_item_with_no_customer_still_counts(self):
		"""History imported before plan items had a customer names it only on the
		event; excluding every event that fulfils an item would lose those visits."""
		event = make_event(REP, self.day(0), self.orgs["history"])
		make_plan(
			REP,
			self.monday,
			[
				{
					"activity_type": "Visit",
					"planned_date": self.day(0),
					"status": "Done",
					"fulfilled_by_doctype": "Event",
					"fulfilled_by": event.name,
				}
			],
		)
		self.assertEqual(self.rows()[self.orgs["history"]]["visits"], 1)

	def test_a_cancelled_or_future_visit_is_not_an_interaction(self):
		make_event(REP, self.day(1), self.orgs["untouched"], status="Cancelled")
		make_event(REP, add_days(nowdate(), 2), self.orgs["untouched"], status="Open")
		row = self.rows()[self.orgs["untouched"]]
		self.assertEqual(row["total"], 0)
		self.assertIsNone(row["last_interaction"])

	def test_an_untouched_customer_is_listed_with_nothing_and_in_the_without_list(self):
		make_event(REP, self.day(1), self.orgs["visited"])
		rows = self.rows()
		untouched = rows[self.orgs["untouched"]]
		self.assertEqual((untouched["total"], untouched["last_interaction"]), (0, None))
		self.assertIsNone(untouched["days_since"])

		without = self.rows(only_without=True)
		self.assertIn(self.orgs["untouched"], without)
		self.assertNotIn(self.orgs["visited"], without)

		report = get_report("customers_without_interaction", self.start, self.end, REP)
		self.assertIn(self.orgs["untouched"], [r["organization"] for r in report["rows"]])

	def test_last_interaction_reaches_back_before_the_period(self):
		earlier = add_days(self.monday, -14)
		make_event(REP, earlier, self.orgs["visited"])
		row = self.rows()[self.orgs["visited"]]
		self.assertEqual(row["total"], 0)
		self.assertEqual(row["last_interaction"], str(getdate(earlier)))
		self.assertEqual(row["days_since"], 20)
		# a customer seen before the period is less neglected than one never seen
		order = [r["organization"] for r in customer_interaction(self.start, self.end, REP)]
		self.assertLess(order.index(self.orgs["untouched"]), order.index(self.orgs["visited"]))

	def test_another_reps_visit_is_not_this_reps_interaction(self):
		make_event(OUTSIDER, self.day(1), self.orgs["visited"])
		self.assertEqual(self.rows()[self.orgs["visited"]]["total"], 0)


class AdherenceCancellationTest(VisitFixture, IntegrationTestCase):
	def test_a_cancelled_item_is_not_due_and_is_counted_once_as_cancelled(self):
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Adherence Cancel Pty"})
			.insert(ignore_permissions=True)
			.name
		)
		# the planner records a cancelled visit as a Cancelled Visit event too
		recording = make_event(REP, self.day(2), org, status="Cancelled")
		# and a cancellation made on the calendar alone, with no plan item
		make_event(REP, self.day(3), org, status="Cancelled")
		make_plan(
			REP,
			self.monday,
			[
				{"activity_type": "Visit", "planned_date": self.day(0), "status": "Done"},
				{"activity_type": "Visit", "planned_date": self.day(1), "status": "Missed"},
				{
					"activity_type": "Visit",
					"planned_date": self.day(2),
					"status": "Cancelled",
					"manual_override": 1,
					"organization": org,
					"fulfilled_by_doctype": "Event",
					"fulfilled_by": recording.name,
				},
			],
		)

		total = plan_adherence(self.start, self.end, REP)[0]
		self.assertEqual((total["planned"], total["done"], total["missed"]), (2, 1, 1))
		self.assertEqual(total["adherence"], 50)
		# the item, plus the calendar-only cancellation; the recording event is the item
		self.assertEqual(total["cancelled"], 2)

		grouped = {r["user"]: r for r in plan_adherence(self.start, self.end, REP, group_by_user=True)}
		self.assertEqual((grouped[REP]["planned"], grouped[REP]["cancelled"]), (2, 2))

	def test_a_rep_whose_only_items_were_cancelled_gets_a_row_with_nothing_due(self):
		make_plan(
			REP,
			self.monday,
			[
				{
					"activity_type": "Visit",
					"planned_date": self.day(1),
					"status": "Cancelled",
					"manual_override": 1,
				}
			],
		)
		rows = plan_adherence(self.start, self.end, REP, group_by_user=True)
		self.assertEqual(len(rows), 1)
		self.assertEqual((rows[0]["planned"], rows[0]["cancelled"]), (0, 1))
		self.assertIsNone(rows[0]["adherence"])
