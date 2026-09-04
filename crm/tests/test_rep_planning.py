# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fulfilment matching tests.

``match_items`` is pure -- plan-item rows and actual-activity rows in,
assignments out -- so the matching rules live here without a site. The
scheduler entry is exercised against the test site at the end, once per
activity kind: the adapter that turns records into actuals is where the
user field, the timestamp and the outcome filter can each be wrong.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm import rep_planning
from crm.install import ensure_visit_event_category
from crm.rep_planning import MATCH_HORIZON_WEEKS, match_actuals, match_items

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

	def test_the_item_naming_the_reference_beats_a_nearer_generic_one(self):
		items = [
			item(name="generic", planned_date=date(2026, 8, 11), reference_docname=None),
			item(name="on-deal", planned_date=date(2026, 8, 13)),
		]
		out = match_items(items, [actual(when=datetime(2026, 8, 11, 9, 0))])
		self.assertEqual(list(out), ["on-deal"])

	def test_equally_good_candidates_resolve_the_same_way_every_run(self):
		items = [item(name="b-item"), item(name="a-item")]
		first = match_items(items, [actual()])
		second = match_items(list(reversed(items)), [actual()])
		self.assertEqual(list(first), ["a-item"])
		self.assertEqual(list(first), list(second))

	def test_a_visit_item_is_fulfilled_by_a_visit_only(self):
		visit = actual(doctype="Event", name="EV-1", kind="Visit")
		self.assertEqual(match_items([item(activity_type="Visit")], [visit])["item-1"]["name"], "EV-1")
		meeting = actual(doctype="Event", name="EV-1", kind="Meeting")
		self.assertEqual(match_items([item(activity_type="Visit")], [meeting]), {})


class MatchActualsJobTest(IntegrationTestCase):
	USER = "rep-planner@crmtest.test"
	OTHER = "rep-planner-two@crmtest.test"

	def setUp(self):
		super().setUp()
		for email, name in ((self.USER, "Rep Planner"), (self.OTHER, "Rep Planner Two")):
			if not frappe.db.exists("User", email):
				user = frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": name,
						"send_welcome_email": 0,
					}
				).insert(ignore_permissions=True)
				user.add_roles("Sales User")
		# frappe rolls the transaction back per class, not per test, so each test
		# clears what the last one left; on a shared dev site that means this
		# suite's own two users and nothing else
		self.clear_fixtures()
		self.addCleanup(self.clear_fixtures)
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Plan Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert().name
		self.monday = self.this_monday()
		self.today = frappe.utils.getdate()

	def clear_fixtures(self):
		users = (self.USER, self.OTHER)
		targets = (
			("CRM Rep Plan", {"user": ("in", users)}, None),
			("CRM Call Log", None, [["caller", "in", users], ["receiver", "in", users]]),
			("Event", {"owner": ("in", users)}, None),
			("Communication", {"owner": ("in", users)}, None),
			("CRM Task", {"assigned_to": ("in", users)}, None),
		)
		for doctype, filters, or_filters in targets:
			for name in frappe.get_all(doctype, filters=filters, or_filters=or_filters, pluck="name"):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)

	def this_monday(self):
		today = frappe.utils.getdate()
		return frappe.utils.add_days(today, -today.weekday())

	def make_plan(self, *items, user=None, week_start=None):
		return frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": user or self.USER,
				"week_start": week_start or self.monday,
				"items": [{"planned_date": self.today, **row} for row in items],
			}
		).insert(ignore_permissions=True)

	def on_deal(self, **fields):
		return {"reference_doctype": "CRM Deal", "reference_docname": self.deal, **fields}

	def make_call(self, **fields):
		return frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"telephony_medium": "Twilio",
				"type": "Outgoing",
				"from": "+27110000000",
				"to": "+27110000001",
				"start_time": frappe.utils.now_datetime(),
				**fields,
			}
		).insert(ignore_permissions=True)

	def test_a_done_task_fulfils_the_planned_item(self):
		plan = self.make_plan(self.on_deal(activity_type="Task"))
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

	def test_a_stale_unfulfilled_item_goes_missed(self):
		old_monday = frappe.utils.add_days(self.monday, -14)
		plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": self.USER,
				"week_start": old_monday,
				"items": [{"activity_type": "Call", "planned_date": old_monday}],
			}
		).insert(ignore_permissions=True)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Missed")

	def test_a_completed_call_the_rep_placed_fulfils_the_item(self):
		plan = self.make_plan(self.on_deal(activity_type="Call"))
		# telephony writes the log as the integration user, so owner is not the rep
		call = self.make_call(
			caller=self.USER,
			status="Completed",
			reference_doctype="CRM Deal",
			reference_docname=self.deal,
		)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")
		self.assertEqual(plan.items[0].fulfilled_by, call.name)

	def test_a_call_the_rep_received_fulfils_the_item(self):
		plan = self.make_plan({"activity_type": "Call"})
		self.make_call(receiver=self.USER, type="Incoming", status="Completed")
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")

	def test_a_call_that_never_connected_does_not_fulfil_the_item(self):
		plan = self.make_plan({"activity_type": "Call"})
		self.make_call(caller=self.USER, status="Failed")
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Planned")

	def test_a_call_is_keyed_on_when_it_happened_not_on_when_it_was_logged(self):
		plan = self.make_plan({"activity_type": "Call"})
		self.make_call(
			caller=self.USER,
			status="Completed",
			start_time=frappe.utils.add_to_date(self.monday, weeks=-3),
		)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Planned")

	def test_a_meeting_on_the_deal_the_item_names_is_fulfilled(self):
		plan = self.make_plan(self.on_deal(activity_type="Meeting"))
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Discovery call",
				"starts_on": frappe.utils.now_datetime(),
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Event", event.name, "owner", self.USER)

		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")
		self.assertEqual(plan.items[0].fulfilled_by, event.name)

	def test_a_cancelled_meeting_does_not_fulfil_the_item(self):
		plan = self.make_plan({"activity_type": "Meeting"})
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Called off",
				"starts_on": frappe.utils.now_datetime(),
				"status": "Cancelled",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Event", event.name, "owner", self.USER)

		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Planned")

	def test_a_sent_email_fulfils_the_item(self):
		plan = self.make_plan({"activity_type": "Email"})
		communication = self.make_communication(subject="Proposal")
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")
		self.assertEqual(plan.items[0].fulfilled_by, communication.name)

	def test_an_automated_message_does_not_fulfil_an_email_item(self):
		plan = self.make_plan({"activity_type": "Email"})
		self.make_communication(subject="Your weekly digest", communication_type="Automated Message")
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Planned")

	def make_communication(self, **fields):
		doc = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Sent",
				"content": "body",
				"reference_doctype": "CRM Deal",
				"reference_name": self.deal,
				**fields,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Communication", doc.name, "owner", self.USER)
		return doc

	def test_a_second_run_changes_nothing(self):
		plan = self.make_plan(self.on_deal(activity_type="Call"))
		self.make_call(
			caller=self.USER,
			status="Completed",
			reference_doctype="CRM Deal",
			reference_docname=self.deal,
		)
		self.assertEqual(match_actuals(), 1)
		plan.reload()
		fulfilled_by = plan.items[0].fulfilled_by

		self.assertEqual(match_actuals(), 0)
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")
		self.assertEqual(plan.items[0].fulfilled_by, fulfilled_by)

	def test_deleting_the_fulfilling_record_takes_the_fulfilment_with_it(self):
		plan = self.make_plan({"activity_type": "Call"})
		call = self.make_call(caller=self.USER, status="Completed")
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")

		frappe.delete_doc("CRM Call Log", call.name, force=True, ignore_permissions=True)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Planned")
		self.assertFalse(plan.items[0].fulfilled_by)

	def test_a_meeting_moved_out_of_the_week_releases_the_item(self):
		plan = self.make_plan({"activity_type": "Meeting"})
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Slipping",
				"starts_on": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Event", event.name, "owner", self.USER)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")

		frappe.db.set_value("Event", event.name, "starts_on", frappe.utils.add_to_date(self.monday, weeks=3))
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Planned")

	def test_a_meeting_recategorised_as_a_visit_releases_the_item(self):
		plan = self.make_plan({"activity_type": "Meeting"})
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Slipping",
				"starts_on": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Event", event.name, "owner", self.USER)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")
		self.assertEqual(plan.items[0].fulfilled_by, event.name)

		frappe.db.set_value("Event", event.name, "event_category", "Visit")
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Planned")
		self.assertFalse(plan.items[0].fulfilled_by)

	def test_a_missed_item_is_reconsidered_once_the_record_shows_up(self):
		last_monday = frappe.utils.add_days(self.monday, -7)
		plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": self.USER,
				"week_start": last_monday,
				"items": [{"activity_type": "Call", "planned_date": last_monday}],
			}
		).insert(ignore_permissions=True)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Missed")

		self.make_call(
			caller=self.USER,
			status="Completed",
			start_time=frappe.utils.add_to_date(last_monday, hours=10),
		)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")

	def test_one_record_is_never_credited_to_two_items(self):
		plan = self.make_plan({"activity_type": "Call"}, {"activity_type": "Call"})
		self.make_call(caller=self.USER, status="Completed")

		match_actuals()
		plan.reload()
		self.assertEqual(sorted(row.status for row in plan.items), ["Done", "Planned"])

		# the second run sees the same call again; the item already holding it keeps it
		match_actuals()
		plan.reload()
		self.assertEqual(sorted(row.status for row in plan.items), ["Done", "Planned"])

		self.make_call(caller=self.USER, status="Completed")
		match_actuals()
		plan.reload()
		self.assertEqual([row.status for row in plan.items], ["Done", "Done"])

	def test_a_manually_corrected_item_survives_the_job(self):
		plan = self.make_plan({"activity_type": "Call"})
		frappe.db.set_value(
			"CRM Rep Plan Item",
			plan.items[0].name,
			{"status": "Done", "manual_override": 1},
		)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")

	def test_items_past_the_matching_horizon_stop_being_open(self):
		stranded_monday = frappe.utils.add_days(self.monday, -7 * (MATCH_HORIZON_WEEKS + 1))
		plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": self.USER,
				"week_start": stranded_monday,
				"items": [{"activity_type": "Task", "planned_date": stranded_monday}],
			}
		).insert(ignore_permissions=True)
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Missed")

	def test_another_reps_activity_never_fulfils_this_reps_item(self):
		plan = self.make_plan({"activity_type": "Call"})
		self.make_call(caller=self.OTHER, status="Completed")
		match_actuals()
		plan.reload()
		self.assertEqual(plan.items[0].status, "Planned")

	def test_a_broken_plan_does_not_abort_the_rest_of_the_run(self):
		broken = self.make_plan({"activity_type": "Call"}, user=self.OTHER)
		plan = self.make_plan(self.on_deal(activity_type="Task"))
		frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Still counted",
				"status": "Done",
				"assigned_to": self.USER,
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal,
			}
		).insert(ignore_permissions=True)

		# plans are walked oldest first, so the broken one is reached first
		real = rep_planning._match_plan

		def explode(row, today, claimed):
			if row.name == broken.name:
				raise ValueError("dangling link")
			return real(row, today, claimed)

		with patch.object(rep_planning, "_match_plan", explode):
			match_actuals()

		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")

	def test_actuals_are_fetched_once_per_source_however_many_plans_there_are(self):
		"""The daily run reads every rep's activity once and slices it per plan;
		the per-plan version was four queries a plan plus one per Done item."""
		for offset in (0, -7, -14):
			monday = frappe.utils.add_days(self.monday, offset)
			for user in (self.USER, self.OTHER):
				self.make_plan(
					{"activity_type": "Task", "planned_date": monday},
					{"activity_type": "Call", "planned_date": monday},
					user=user,
					week_start=monday,
				)
		with patch.object(rep_planning, "_query_source", wraps=rep_planning._query_source) as queries:
			match_actuals()
		self.assertEqual(queries.call_count, len(rep_planning.ACTUAL_SOURCES))

	def test_a_rolled_back_plan_leaves_no_claim_behind(self):
		"""A plan that fails after claiming a record must not keep that record
		from the plan that is then matched successfully."""
		last_monday = frappe.utils.add_days(self.monday, -7)
		broken = self.make_plan(
			{"activity_type": "Task", "planned_date": last_monday}, week_start=last_monday
		)
		plan = self.make_plan(self.on_deal(activity_type="Task"))
		frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Claimed then released",
				"status": "Done",
				"assigned_to": self.USER,
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal,
			}
		).insert(ignore_permissions=True)

		real = rep_planning._match_plan

		def claim_then_explode(row, today, claimed):
			if row.name == broken.name:
				claimed[("CRM Task", "stray")] = row.name
				raise ValueError("after claiming")
			return real(row, today, claimed)

		with patch.object(rep_planning, "_match_plan", claim_then_explode):
			match_actuals()

		plan.reload()
		self.assertEqual(plan.items[0].status, "Done")
		self.assertNotIn(("CRM Task", "stray"), rep_planning._claimed_actuals(self.monday))

	def test_a_week_old_plan_settles_within_the_horizon(self):
		"""The horizon sweep must not touch weeks the matcher still visits."""
		last_monday = frappe.utils.add_days(self.monday, -7)
		plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": self.USER,
				"week_start": last_monday,
				"items": [
					{"activity_type": "Task", "planned_date": last_monday},
					{"activity_type": "Task", "planned_date": last_monday + timedelta(days=1)},
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"CRM Rep Plan Item",
			plan.items[1].name,
			{"status": "Done", "manual_override": 1},
		)
		match_actuals()
		plan.reload()
		self.assertEqual([row.status for row in plan.items], ["Missed", "Done"])


class EventKindsTest(IntegrationTestCase):
	"""One Event is emitted under exactly one kind, or a single visit could fulfil
	a Visit item and a Meeting item in the same run."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_visit_event_category()

	def tearDown(self):
		frappe.db.rollback()

	def _event(self, subject, category=None):
		fields = {
			"doctype": "Event",
			"subject": subject,
			"starts_on": datetime(2026, 8, 12, 10, 0),
			"event_type": "Private",
		}
		if category:
			fields["event_category"] = category
		return frappe.get_doc(fields).insert()

	def test_visit_and_meeting_partition_events_by_category(self):
		visit = self._event("Site visit", "Visit")
		meeting = self._event("Catch-up")
		window = (date(2026, 8, 10), date(2026, 8, 16))
		visits = {row["name"] for row in rep_planning._query_source("Visit", "Administrator", window)}
		meetings = {row["name"] for row in rep_planning._query_source("Meeting", "Administrator", window)}
		self.assertIn(visit.name, visits)
		self.assertNotIn(meeting.name, visits)
		self.assertIn(meeting.name, meetings)
		self.assertNotIn(visit.name, meetings)

	def test_the_reverse_map_still_names_meeting_for_an_event(self):
		self.assertEqual(rep_planning.KIND_BY_DOCTYPE["Event"], "Meeting")
