# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Closing planned work by hand: outcomes, cancellations, typed logging, the team week.

MBP's managers asked for the old rep app's habits to carry over: every
activity is planned against a customer, nothing is ticked off without saying
what happened, a cancelled visit is not a missed one, and a manager can see
the whole team's week at once.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.rep_plan import (
	cancel_item,
	clear_override,
	complete_item,
	get_team_week,
	log_unplanned_visit,
	mark_missed,
	save_plan,
)
from crm.install import ensure_visit_event_category
from crm.rep_planning import match_actuals

REP = "outcome-rep@crmtest.test"
OTHER = "outcome-other@crmtest.test"


def make_sales_user(email: str, first_name: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first_name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


def this_monday() -> str:
	today = frappe.utils.getdate()
	return str(today - timedelta(days=today.weekday()))


def today() -> str:
	return str(frappe.utils.getdate())


class OutcomeTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_visit_event_category()

	def setUp(self):
		super().setUp()
		make_sales_user(REP, "Outcome Rep")
		make_sales_user(OTHER, "Outcome Other")
		self.org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Outcome Platinum Springs"}
		).insert(ignore_if_duplicate=True)
		self.other_org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Outcome Canyon Coal"}
		).insert(ignore_if_duplicate=True)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(REP)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def plan_one(self, activity_type="Visit", organization=None, planned_date=None) -> str:
		plan = save_plan(
			this_monday(),
			[
				{
					"activity_type": activity_type,
					"planned_date": planned_date or today(),
					"note": "Quotation follow-up",
					"organization": organization if organization is not None else self.org.name,
				}
			],
		)
		return plan["items"][0]["name"]


class PlanAgainstACustomerTest(OutcomeTestCase):
	def test_a_planned_item_keeps_its_customer(self):
		self.plan_one()
		stored = frappe.get_all("CRM Rep Plan Item", filters={"organization": self.org.name}, pluck="name")
		self.assertEqual(len(stored), 1)

	def test_a_customer_that_no_longer_exists_is_dropped_not_fatal(self):
		plan = save_plan(
			this_monday(),
			[{"activity_type": "Visit", "planned_date": today(), "organization": "Gone Mining Ltd"}],
		)
		self.assertIsNone(plan["items"][0]["organization"])


class CompleteItemTest(OutcomeTestCase):
	def test_a_visit_is_closed_with_its_outcome_and_a_visit_event_at_the_customer(self):
		item = self.plan_one()
		plan = complete_item(item, "Replaced the 350mm knife gate; quote for two more")
		row = plan["items"][0]
		self.assertEqual(row["status"], "Done")
		self.assertEqual(row["manual_override"], 1)
		self.assertEqual(row["outcome"], "Replaced the 350mm knife gate; quote for two more")
		self.assertEqual(row["fulfilled_by_doctype"], "Event")
		event = frappe.get_doc("Event", row["fulfilled_by"])
		self.assertEqual((event.event_category, event.status, event.owner), ("Visit", "Completed", REP))
		self.assertEqual([p.reference_docname for p in event.event_participants], [self.org.name])
		self.assertEqual(plan["rollup"]["Visit"]["done"], 1)

	def test_nothing_is_ticked_off_without_saying_what_happened(self):
		item = self.plan_one()
		with self.assertRaises(frappe.ValidationError):
			complete_item(item, "   ")

	def test_a_call_is_closed_on_the_reps_word_without_a_calendar_event(self):
		item = self.plan_one("Call")
		row = complete_item(item, "Spoke to the buyer")["items"][0]
		self.assertEqual(row["status"], "Done")
		self.assertIsNone(row["fulfilled_by"])

	def test_an_activity_cannot_be_completed_before_it_happens(self):
		item = self.plan_one()
		with self.assertRaises(frappe.ValidationError):
			complete_item(item, "not yet", when=str(frappe.utils.now_datetime() + timedelta(hours=2)))

	def test_another_reps_item_cannot_be_closed(self):
		item = self.plan_one()
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			complete_item(item, "I was there too")

	def test_a_completed_item_is_not_completed_twice(self):
		item = self.plan_one()
		complete_item(item, "Done")
		with self.assertRaises(frappe.ValidationError):
			complete_item(item, "Done again")


class CancelItemTest(OutcomeTestCase):
	def test_a_cancelled_visit_is_cancelled_not_missed_and_leaves_a_cancelled_event(self):
		item = self.plan_one()
		plan = cancel_item(item, "Plant shut for maintenance")
		row = plan["items"][0]
		self.assertEqual((row["status"], row["manual_override"]), ("Cancelled", 1))
		self.assertEqual(row["outcome"], "Plant shut for maintenance")
		event = frappe.get_doc("Event", row["fulfilled_by"])
		self.assertEqual((event.event_category, event.status), ("Visit", "Cancelled"))
		self.assertEqual(plan["rollup"]["Visit"]["cancelled"], 1)

	def test_a_reason_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			cancel_item(self.plan_one(), "")

	def test_changing_your_mind_takes_the_cancelled_event_with_it(self):
		item = self.plan_one()
		event = cancel_item(item, "Customer moved it")["items"][0]["fulfilled_by"]
		mark_missed(item)
		self.assertFalse(frappe.db.exists("Event", event))

		item2 = self.plan_one()
		event2 = cancel_item(item2, "Customer moved it")["items"][0]["fulfilled_by"]
		row = next(i for i in clear_override(item2)["items"] if i["name"] == item2)
		self.assertFalse(frappe.db.exists("Event", event2))
		self.assertEqual((row["status"], row["outcome"]), ("Planned", None))

	def test_completing_a_cancelled_visit_replaces_the_cancellation(self):
		item = self.plan_one()
		cancelled = cancel_item(item, "Moved")["items"][0]["fulfilled_by"]
		row = complete_item(item, "Went after all")["items"][0]
		# frappe hands a deleted event's number to the next one (revert_series_if_last),
		# so the check is on the status, not on the name being gone
		self.assertFalse(frappe.db.exists("Event", {"name": cancelled, "status": "Cancelled"}))
		self.assertEqual(frappe.db.get_value("Event", row["fulfilled_by"], "status"), "Completed")

	def test_a_cancelled_admin_item_needs_no_event(self):
		row = cancel_item(self.plan_one("Admin", organization=""), "Office closed")["items"][0]
		self.assertEqual(row["status"], "Cancelled")
		self.assertIsNone(row["fulfilled_by"])


class LogActivityTest(OutcomeTestCase):
	def test_a_delivery_is_logged_against_the_customer(self):
		row = log_unplanned_visit(self.org.name, "Dropped off 4 actuators", activity_type="Delivery")[
			"items"
		][0]
		self.assertEqual(
			(row["activity_type"], row["status"], row["organization"]), ("Delivery", "Done", self.org.name)
		)
		event = frappe.get_doc("Event", row["fulfilled_by"])
		self.assertTrue(event.subject.startswith("Delivery"))

	def test_a_visit_kind_needs_a_customer(self):
		with self.assertRaises(frappe.ValidationError):
			log_unplanned_visit(None, "Somewhere", activity_type="Unplanned Meeting")

	def test_admin_needs_no_customer_and_no_event(self):
		row = log_unplanned_visit(None, "Visit reports for the week", activity_type="Reports")["items"][0]
		self.assertEqual(row["activity_type"], "Reports")
		self.assertIsNone(row["fulfilled_by"])

	def test_a_long_account_is_kept_whole_in_the_outcome(self):
		text = "Called to site. " * 20
		row = log_unplanned_visit(self.org.name, text)["items"][0]
		self.assertLessEqual(len(row["note"]), 140)
		self.assertEqual(row["outcome"], text.strip())

	def test_meetings_and_tasks_are_not_logged_here(self):
		with self.assertRaises(frappe.ValidationError):
			log_unplanned_visit(self.org.name, "x", activity_type="Task")


class TeamWeekTest(OutcomeTestCase):
	def test_a_rep_sees_only_their_own_row(self):
		self.plan_one()
		week = get_team_week(this_monday())
		self.assertEqual([rep["user"] for rep in week["reps"]], [REP])
		self.assertEqual(len(week["reps"][0]["items"]), 1)
		self.assertEqual(week["reps"][0]["items"][0]["organization"], self.org.name)

	def test_an_administrator_sees_every_reps_row(self):
		self.plan_one()
		frappe.set_user(OTHER)
		self.plan_one("Call")
		frappe.set_user("Administrator")
		week = get_team_week(this_monday())
		by_user = {rep["user"]: rep for rep in week["reps"]}
		self.assertEqual(len(by_user[REP]["items"]), 1)
		self.assertEqual(by_user[OTHER]["rollup"]["Call"]["planned"], 1)

	def test_the_week_must_start_on_a_monday(self):
		with self.assertRaises(frappe.ValidationError):
			get_team_week(str(frappe.utils.add_days(this_monday(), 1)))


class MatchOnCustomerTest(OutcomeTestCase):
	def _visit_at(self, organization):
		return frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Visit",
				# the start of today: always in this week and never after now, where
				# "five minutes ago" was last week for five minutes every Monday
				"starts_on": datetime.combine(frappe.utils.getdate(), time.min),
				"event_type": "Private",
				"event_category": "Visit",
				"status": "Completed",
				"event_participants": [
					{"reference_doctype": "CRM Organization", "reference_docname": organization}
				],
			}
		).insert()

	def test_a_visit_at_another_customer_does_not_fulfil_the_plan(self):
		item = self.plan_one()
		self._visit_at(self.other_org.name)
		frappe.set_user("Administrator")
		match_actuals()
		self.assertNotEqual(frappe.db.get_value("CRM Rep Plan Item", item, "status"), "Done")

	def test_a_visit_at_the_planned_customer_does(self):
		item = self.plan_one()
		event = self._visit_at(self.org.name)
		frappe.set_user("Administrator")
		match_actuals()
		self.assertEqual(
			frappe.db.get_value("CRM Rep Plan Item", item, ["status", "fulfilled_by"]), ("Done", event.name)
		)


class BackfillCustomerPatchTest(OutcomeTestCase):
	def test_an_item_gets_the_customer_of_the_event_that_fulfils_it(self):
		from crm.patches.v1_0.backfill_plan_item_customer import execute

		# planned first: saving a week replaces its items, logging appends
		untouched = self.plan_one("Call", organization="")
		row = log_unplanned_visit(self.org.name, "Breakdown call-out")["items"][-1]
		frappe.db.set_value("CRM Rep Plan Item", row["name"], "organization", None)
		execute()
		self.assertEqual(frappe.db.get_value("CRM Rep Plan Item", row["name"], "organization"), self.org.name)
		self.assertFalse(frappe.db.get_value("CRM Rep Plan Item", untouched, "organization"))


class ReferenceScopeTest(OutcomeTestCase):
	"""A rep plans and logs only against deals they may read: the reference
	reaches the visit event, and through it client_reliability would show the
	other rep's deal's organization."""

	def deal_of(self, owner):
		frappe.set_user("Administrator")
		deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.org.name, "deal_owner": owner}
		).insert(ignore_permissions=True)
		frappe.set_user(REP)
		return deal.name

	def test_a_deal_the_rep_cannot_read_is_dropped_from_the_plan(self):
		theirs, mine = self.deal_of(OTHER), self.deal_of(REP)
		plan = save_plan(
			this_monday(),
			[
				{
					"activity_type": "Visit",
					"planned_date": today(),
					"note": "theirs",
					"reference_doctype": "CRM Deal",
					"reference_docname": theirs,
				},
				{
					"activity_type": "Visit",
					"planned_date": today(),
					"note": "mine",
					"reference_doctype": "CRM Deal",
					"reference_docname": mine,
				},
			],
		)
		refs = {i["note"]: i["reference_docname"] for i in plan["items"]}
		self.assertEqual(refs, {"theirs": None, "mine": mine})

	def test_a_visit_cannot_be_logged_against_a_deal_the_rep_cannot_read(self):
		theirs = self.deal_of(OTHER)
		with self.assertRaises(frappe.PermissionError):
			log_unplanned_visit(self.org.name, "x", reference_doctype="CRM Deal", reference_docname=theirs)


class DoneAndCancelledDoNotOverlapTest(OutcomeTestCase):
	def test_a_done_item_cannot_be_cancelled_over_its_visit(self):
		item = self.plan_one()
		complete_item(item, "Went")
		with self.assertRaises(frappe.ValidationError):
			cancel_item(item, "Changed my mind")

	def test_marking_a_cancelled_item_done_takes_the_cancelled_event_with_it(self):
		from crm.api.rep_plan import mark_fulfilled

		item = self.plan_one()
		event = cancel_item(item, "Moved")["items"][0]["fulfilled_by"]
		mark_fulfilled(item)
		self.assertFalse(frappe.db.exists("Event", {"name": event, "status": "Cancelled"}))


class ServerOwnedFieldsTest(OutcomeTestCase):
	"""An item's status and fulfilment are written by the server, never a client.

	The planner endpoints only ever took the editable fields, but the generic
	document API saves the rep's own plan too, and nothing refused the rest: a rep
	pointed her item at a colleague's Cancelled visit and clear_override then
	deleted it, permissions bypassed.
	"""

	def colleagues_cancelled_visit(self) -> str:
		frappe.set_user(OTHER)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Visit: Outcome Canyon Coal",
				"starts_on": frappe.utils.now_datetime(),
				"event_type": "Private",
				"event_category": "Visit",
				"status": "Cancelled",
			}
		).insert(ignore_permissions=True)
		frappe.set_user(REP)
		return event.name

	def test_the_document_api_cannot_write_an_items_fulfilment(self):
		victim = self.colleagues_cancelled_visit()
		item = self.plan_one()
		for values in (
			{"status": "Cancelled", "fulfilled_by_doctype": "Event", "fulfilled_by": victim},
			{"status": "Done", "manual_override": 1},
			{"outcome": "Went"},
		):
			with self.subTest(values=values), self.assertRaises(frappe.PermissionError):
				frappe.client.set_value("CRM Rep Plan Item", item, values)
		stored = frappe.db.get_value("CRM Rep Plan Item", item, ["status", "fulfilled_by"], as_dict=True)
		self.assertEqual((stored.status, stored.fulfilled_by), ("Planned", None))

		# a new row is no way round it either
		plan = frappe.db.get_value("CRM Rep Plan Item", item, "parent")
		with self.assertRaises(frappe.PermissionError):
			frappe.client.insert(
				{
					"doctype": "CRM Rep Plan Item",
					"parenttype": "CRM Rep Plan",
					"parentfield": "items",
					"parent": plan,
					"activity_type": "Visit",
					"planned_date": today(),
					"status": "Cancelled",
					"fulfilled_by_doctype": "Event",
					"fulfilled_by": victim,
				}
			)

		# what a client may edit still goes through
		frappe.client.set_value("CRM Rep Plan Item", item, "note", "After lunch")
		self.assertEqual(frappe.db.get_value("CRM Rep Plan Item", item, "note"), "After lunch")

	def colleagues_meeting(self) -> str:
		frappe.set_user(OTHER)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Meeting: Outcome Canyon Coal",
				"starts_on": frappe.utils.now_datetime(),
				"event_type": "Private",
				"status": "Completed",
			}
		).insert(ignore_permissions=True)
		frappe.set_user(REP)
		return event.name

	def test_an_item_is_not_saved_on_its_own(self):
		"""The row-level routes never save the plan, or re-save one that reads the
		row back unchanged, so CRMRepPlan.validate never saw the claim."""
		from frappe.api.v2 import create_doc, update_doc

		victim = self.colleagues_meeting()
		item = self.plan_one(activity_type="Meeting")
		claim = {
			"status": "Done",
			"manual_override": 1,
			"fulfilled_by_doctype": "Event",
			"fulfilled_by": victim,
		}

		def as_rest_body(data):
			form_dict = frappe.local.form_dict
			self.addCleanup(setattr, frappe.local, "form_dict", form_dict)
			frappe.local.form_dict = frappe._dict(data)

		row = frappe.get_doc("CRM Rep Plan Item", item).as_dict()
		with self.subTest("frappe.client.save"), self.assertRaises(frappe.PermissionError):
			frappe.client.save({**row, **claim})

		with self.subTest("PUT /api/resource"), self.assertRaises(frappe.PermissionError):
			as_rest_body(claim)
			update_doc("CRM Rep Plan Item", item)

		with self.subTest("POST /api/resource"), self.assertRaises(frappe.PermissionError):
			as_rest_body(
				{
					"parenttype": "CRM Rep Plan",
					"parentfield": "items",
					"parent": row.parent,
					"activity_type": "Meeting",
					"planned_date": today(),
					**claim,
				}
			)
			create_doc("CRM Rep Plan Item")

		stored = frappe.db.get_value("CRM Rep Plan Item", item, ["status", "fulfilled_by"], as_dict=True)
		self.assertEqual((stored.status, stored.fulfilled_by), ("Planned", None))
		self.assertEqual(frappe.db.count("CRM Rep Plan Item", {"parent": row.parent}), 1)
		self.assertFalse(frappe.db.exists("CRM Rep Plan Item", {"fulfilled_by": victim}))

	def test_a_colleagues_item_is_not_pulled_into_the_reps_plan(self):
		"""A row that names an item frappe cannot find in this plan has no stored
		copy, which read as a new row at its defaults; the save then UPDATEd that
		item by name, moving it out of the colleague's week and wiping its status."""
		frappe.set_user(OTHER)
		theirs = save_plan(this_monday(), [{"activity_type": "Visit", "planned_date": today()}])["items"][0]
		their_plan = frappe.db.get_value("CRM Rep Plan Item", theirs["name"], "parent")
		frappe.set_user("Administrator")
		event = self.colleagues_cancelled_visit()
		frappe.db.set_value(
			"CRM Rep Plan Item",
			theirs["name"],
			{"status": "Done", "manual_override": 1, "fulfilled_by_doctype": "Event", "fulfilled_by": event},
		)
		frappe.set_user(REP)
		self.plan_one()
		mine = frappe.get_doc("CRM Rep Plan", {"user": REP, "week_start": this_monday()}).as_dict()
		mine["items"].append({"name": theirs["name"], "activity_type": "Visit", "planned_date": today()})

		with self.assertRaises(frappe.PermissionError):
			frappe.client.save(mine)

		stored = frappe.db.get_value(
			"CRM Rep Plan Item", theirs["name"], ["parent", "status", "fulfilled_by"], as_dict=True
		)
		self.assertEqual((stored.parent, stored.status, stored.fulfilled_by), (their_plan, "Done", event))

	def test_only_the_reps_own_cancellation_is_deleted(self):
		"""Defence in depth for however an item came to name someone else's event:
		the planner deletes its events with permissions off, so it checks what it deletes."""
		victim = self.colleagues_cancelled_visit()
		item = self.plan_one()
		frappe.db.set_value(
			"CRM Rep Plan Item",
			item,
			{
				"status": "Cancelled",
				"manual_override": 1,
				"fulfilled_by_doctype": "Event",
				"fulfilled_by": victim,
			},
		)

		clear_override(item)

		self.assertTrue(frappe.db.exists("Event", victim))


class CorrectingACompletedVisitTest(OutcomeTestCase):
	"""One visit, one event. "Log the outcome" puts a Completed Visit event on the
	calendar; marking the item missed or handing it back used to unlink that event
	and leave it there, where the visit counts and customer interaction still
	counted it -- twice once the visit was logged again, and both ways once it
	was then cancelled."""

	def own_visit(self) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Event",
					"subject": "Visit",
					"starts_on": datetime.combine(frappe.utils.getdate(), time.min),
					"event_type": "Private",
					"event_category": "Visit",
					"status": "Completed",
					"event_participants": [
						{"reference_doctype": "CRM Organization", "reference_docname": self.org.name}
					],
				}
			)
			.insert()
			.name
		)

	def test_marking_a_logged_visit_missed_takes_its_event_with_it(self):
		item = self.plan_one()
		first = complete_item(item, "Visited, quoted two valves")["items"][0]["fulfilled_by"]
		mark_missed(item)
		self.assertFalse(frappe.db.exists("Event", first))

		second = complete_item(item, "Visited after all")["items"][0]["fulfilled_by"]
		self.assertEqual(frappe.db.get_value("Event", second, "status"), "Completed")

	def test_handing_a_logged_visit_back_takes_its_event_with_it(self):
		item = self.plan_one()
		logged = complete_item(item, "Visited")["items"][0]["fulfilled_by"]
		clear_override(item)
		self.assertFalse(frappe.db.exists("Event", logged))

		# the path cancel_item's own message prescribes: no Completed event left behind
		cancelled = cancel_item(item, "Customer moved it")["items"][0]["fulfilled_by"]
		self.assertEqual(frappe.db.get_value("Event", cancelled, "status"), "Cancelled")
		self.assertFalse(frappe.db.exists("Event", {"name": logged, "status": "Completed"}))

	def test_a_visit_the_matcher_found_is_a_record_and_stays(self):
		item = self.plan_one()
		event = self.own_visit()
		frappe.set_user("Administrator")
		match_actuals()
		frappe.set_user(REP)
		self.assertEqual(frappe.db.get_value("CRM Rep Plan Item", item, "fulfilled_by"), event)

		mark_missed(item)
		self.assertTrue(frappe.db.exists("Event", event))

	def test_a_visit_named_by_hand_is_a_record_and_stays(self):
		from crm.api.rep_plan import mark_fulfilled

		item = self.plan_one()
		# a cancellation's reason is not an account of the visit named afterwards
		cancel_item(item, "Customer moved it")
		event = self.own_visit()
		mark_fulfilled(item, "Event", event)
		self.assertIsNone(frappe.db.get_value("CRM Rep Plan Item", item, "outcome"))

		clear_override(item)
		self.assertTrue(frappe.db.exists("Event", event))

	def test_re_marking_done_without_a_record_keeps_the_account(self):
		from crm.api.rep_plan import mark_fulfilled

		item = self.plan_one("Call")
		complete_item(item, "Spoke to the buyer")
		mark_fulfilled(item)
		self.assertEqual(frappe.db.get_value("CRM Rep Plan Item", item, "outcome"), "Spoke to the buyer")
