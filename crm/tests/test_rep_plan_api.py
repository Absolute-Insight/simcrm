# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Rep-plan endpoint tests: ownership, upsert, overrides and the propose-week gate."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.rep_plan import (
	clear_override,
	get_plan,
	get_visible_reps,
	mark_fulfilled,
	mark_missed,
	propose_week,
	save_plan,
)
from crm.rep_planning import MATCH_HORIZON_WEEKS

REP = "plan-rep@crmtest.test"
OTHER = "plan-other@crmtest.test"
LEAD = "plan-lead@crmtest.test"
USERS = (REP, OTHER, LEAD)


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
		for email, name in ((REP, "Plan Rep"), (OTHER, "Plan Other"), (LEAD, "Plan Lead")):
			make_sales_user(email, name)
		# the dev site is shared: clear this suite's own rows, never the tables
		self.clear_fixtures()
		self.addCleanup(self.clear_fixtures)
		self.addCleanup(frappe.set_user, frappe.session.user)
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Plan API Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert().name
		today = frappe.utils.getdate()
		self.monday = str(frappe.utils.add_days(today, -today.weekday()))

	def clear_fixtures(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("CRM Rep Plan", filters={"user": ("in", USERS)}, pluck="name"):
			frappe.delete_doc("CRM Rep Plan", name, force=True, ignore_permissions=True)
		frappe.db.delete("CRM Suggestion", {"user": ("in", USERS)})
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", USERS)})
		frappe.cache.delete_value("crm_sales_hierarchy_subtree")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 0)

	def make_suggestion(self, user, title="Re-engage Plan API Org", action_payload=None):
		doc = {
			"doctype": "CRM Suggestion",
			"signal": "idle_deal",
			"title": title,
			"reference_doctype": "CRM Deal",
			"reference_docname": self.deal,
			"user": user,
			"status": "Open",
			"suggested_action": "schedule_call",
			"score": 70,
		}
		if action_payload is not None:
			doc["action_payload"] = frappe.as_json(action_payload)
		return frappe.get_doc(doc).insert(ignore_permissions=True).name

	def make_task(self, assigned_to: str | None = None) -> str:
		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Fulfilment stand-in",
				"status": "Done",
				"assigned_to": assigned_to,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Task", task.name, force=True)
		return str(task.name)

	def make_hierarchy(self, manager: str, *reports: str):
		"""A one-level sales tree, the same structure that scopes leads and deals."""
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		top = frappe.get_doc(
			{"doctype": "CRM Sales Hierarchy", "user": manager, "full_name": "Plan Lead"}
		).insert(ignore_permissions=True)
		for report in reports:
			frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": report, "reports_to": top.name}).insert(
				ignore_permissions=True
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

	def test_a_week_older_than_the_matching_horizon_cannot_be_saved(self):
		frappe.set_user(REP)
		stranded = str(
			frappe.utils.add_days(frappe.utils.getdate(self.monday), -7 * (MATCH_HORIZON_WEEKS + 1))
		)
		with self.assertRaises(frappe.ValidationError):
			save_plan(stranded, [{"activity_type": "Task", "planned_date": stranded}])

	def test_items_must_be_a_bounded_list(self):
		"""A non-list payload used to fall through to ``plan.append`` and 500; a
		list with no ceiling was an unbounded child table in one request."""
		from crm.api.rep_plan import MAX_PLAN_ITEMS

		frappe.set_user(REP)
		for bad in ('{"activity_type": "Call"}', "not json", 42, [1, 2]):
			with self.assertRaises(frappe.ValidationError):
				save_plan(self.monday, bad)
		too_many = [{"activity_type": "Call", "planned_date": self.monday}] * (MAX_PLAN_ITEMS + 1)
		with self.assertRaises(frappe.ValidationError):
			save_plan(self.monday, too_many)
		self.assertFalse(frappe.db.exists("CRM Rep Plan", {"user": REP, "week_start": self.monday}))

	def test_an_item_cannot_reference_an_arbitrary_doctype(self):
		frappe.set_user(REP)
		with self.assertRaises(frappe.ValidationError):
			save_plan(
				self.monday,
				[
					{
						"activity_type": "Task",
						"planned_date": self.monday,
						"reference_doctype": "User",
						"reference_docname": OTHER,
					}
				],
			)

	def test_propose_week_drafts_from_own_suggestions_and_writes_nothing(self):
		suggestion = self.make_suggestion(REP)
		self.make_suggestion(OTHER)  # someone else's — must not appear
		frappe.set_user(REP)
		drafts = propose_week(self.monday)
		self.assertEqual(len(drafts), 1)
		self.assertEqual(drafts[0]["activity_type"], "Call")
		self.assertEqual(drafts[0]["suggestion"], suggestion)
		self.assertEqual(frappe.db.count("CRM Rep Plan", {"user": REP}), 0)
		self.assertEqual(frappe.db.get_value("CRM Suggestion", suggestion, "status"), "Open")

	def test_propose_week_never_drafts_onto_a_day_already_gone(self):
		for _ in range(6):
			self.make_suggestion(REP)
		frappe.set_user(REP)
		drafts = propose_week(self.monday)
		today = frappe.utils.getdate()
		self.assertTrue(drafts)
		for draft in drafts:
			self.assertGreaterEqual(frappe.utils.getdate(draft["planned_date"]), today)

	def test_propose_week_notes_the_activity_not_the_nagging(self):
		"""A stale_plan suggestion is titled after the miss, not after the work.

		Drafting from the title wrote "Overdue plan item: Call Acme" onto the
		card, and because find_stale_plan_items reads plan notes back, missing
		that draft would title the next one "Overdue plan item: Overdue plan
		item: Call Acme".
		"""
		self.make_suggestion(
			REP,
			title="Overdue plan item: Call Plan API Org",
			action_payload={"title": "Call Plan API Org"},
		)
		frappe.set_user(REP)
		drafts = propose_week(self.monday)
		self.assertEqual(drafts[0]["note"], "Call Plan API Org")

	def test_propose_week_falls_back_to_the_title_without_a_payload(self):
		self.make_suggestion(REP, title="Re-engage Plan API Org")
		frappe.set_user(REP)
		drafts = propose_week(self.monday)
		self.assertEqual(drafts[0]["note"], "Re-engage Plan API Org")

	def test_saving_a_proposed_plan_accepts_its_suggestions(self):
		suggestion = self.make_suggestion(REP)
		frappe.set_user(REP)
		drafts = propose_week(self.monday)
		save_plan(self.monday, drafts)
		self.assertEqual(frappe.db.get_value("CRM Suggestion", suggestion, "status"), "Accepted")

	def test_dropping_a_planned_item_puts_its_suggestion_back_in_the_inbox(self):
		suggestion = self.make_suggestion(REP)
		frappe.set_user(REP)
		save_plan(self.monday, propose_week(self.monday))
		save_plan(self.monday, [])
		self.assertEqual(frappe.db.get_value("CRM Suggestion", suggestion, "status"), "Open")

	def test_another_users_suggestion_is_not_accepted_by_naming_it(self):
		suggestion = self.make_suggestion(OTHER)
		frappe.set_user(REP)
		save_plan(
			self.monday,
			[{"activity_type": "Call", "planned_date": self.monday, "suggestion": suggestion}],
		)
		self.assertEqual(frappe.db.get_value("CRM Suggestion", suggestion, "status"), "Open")

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

	def test_rescheduling_an_item_keeps_its_identity_and_its_matcher_state(self):
		frappe.set_user(REP)
		out = save_plan(self.monday, [{"activity_type": "Task", "planned_date": self.monday, "note": "move"}])
		item_name = out["items"][0]["name"]
		task = self.make_task()
		frappe.db.set_value(
			"CRM Rep Plan Item",
			item_name,
			{"status": "Done", "fulfilled_by_doctype": "CRM Task", "fulfilled_by": task},
		)

		wednesday = str(frappe.utils.add_days(frappe.utils.getdate(self.monday), 2))
		out = save_plan(
			self.monday,
			[{"name": item_name, "activity_type": "Task", "planned_date": wednesday, "note": "move"}],
		)
		item = out["items"][0]
		self.assertEqual(item["name"], item_name)
		self.assertEqual(str(item["planned_date"]), wednesday)
		self.assertEqual(item["status"], "Done")
		self.assertEqual(item["fulfilled_by"], task)

	def test_a_stale_tab_is_told_rather_than_allowed_to_clobber(self):
		frappe.set_user(REP)
		stale = save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		save_plan(self.monday, [{"activity_type": "Task", "planned_date": self.monday}])

		with self.assertRaises(frappe.TimestampMismatchError):
			save_plan(self.monday, stale["items"], modified=stale["modified"])
		out = get_plan(self.monday)
		self.assertEqual(out["items"][0]["activity_type"], "Task")

	def test_a_rep_can_mark_an_item_done_by_hand_and_hand_it_back(self):
		frappe.set_user(REP)
		out = save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		item_name = out["items"][0]["name"]

		out = mark_fulfilled(item_name)
		self.assertEqual(out["items"][0]["status"], "Done")
		self.assertEqual(out["items"][0]["manual_override"], 1)

		out = mark_missed(item_name)
		self.assertEqual(out["items"][0]["status"], "Missed")
		self.assertEqual(out["items"][0]["manual_override"], 1)

		out = clear_override(item_name)
		self.assertEqual(out["items"][0]["status"], "Planned")
		self.assertEqual(out["items"][0]["manual_override"], 0)

	def test_a_manual_override_survives_a_replan(self):
		frappe.set_user(REP)
		out = save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		item_name = out["items"][0]["name"]
		mark_fulfilled(
			item_name, fulfilled_by_doctype="CRM Task", fulfilled_by=self.make_task(assigned_to=REP)
		)

		out = save_plan(
			self.monday,
			[{"name": item_name, "activity_type": "Call", "planned_date": self.monday, "note": "same"}],
		)
		self.assertEqual(out["items"][0]["manual_override"], 1)
		self.assertEqual(out["items"][0]["status"], "Done")

	def test_a_rep_cannot_override_another_reps_item(self):
		frappe.set_user(REP)
		out = save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		item_name = out["items"][0]["name"]
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			mark_fulfilled(item_name)
		self.assertEqual(frappe.db.get_value("CRM Rep Plan Item", item_name, "status"), "Planned")

	def test_only_a_known_activity_doctype_can_be_named_as_the_fulfilment(self):
		frappe.set_user(REP)
		out = save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		with self.assertRaises(frappe.ValidationError):
			mark_fulfilled(out["items"][0]["name"], fulfilled_by_doctype="User", fulfilled_by=OTHER)

	def test_mark_fulfilled_refuses_a_record_that_does_not_exist(self):
		frappe.set_user(REP)
		out = save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		item_name = out["items"][0]["name"]
		with self.assertRaises(frappe.ValidationError):
			mark_fulfilled(item_name, fulfilled_by_doctype="CRM Call Log", fulfilled_by="no-such-call")
		self.assertEqual(frappe.db.get_value("CRM Rep Plan Item", item_name, "status"), "Planned")

	def test_mark_fulfilled_refuses_another_reps_record(self):
		"""A bogus claim is not only wrong for this item: _claimed_actuals
		indexes claims across every plan in the horizon, so it would exclude the
		real record from its own rep's matching and dock their adherence."""
		theirs = frappe.get_doc(
			{"doctype": "CRM Task", "title": "Someone else's work", "status": "Done", "assigned_to": OTHER}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Task", theirs.name, force=True)
		frappe.set_user(REP)
		out = save_plan(self.monday, [{"activity_type": "Task", "planned_date": self.monday}])
		with self.assertRaises(frappe.ValidationError):
			mark_fulfilled(
				out["items"][0]["name"], fulfilled_by_doctype="CRM Task", fulfilled_by=str(theirs.name)
			)

	def test_mark_fulfilled_accepts_the_callers_own_completed_work(self):
		frappe.set_user(REP)
		out = save_plan(self.monday, [{"activity_type": "Task", "planned_date": self.monday}])
		out = mark_fulfilled(
			out["items"][0]["name"],
			fulfilled_by_doctype="CRM Task",
			fulfilled_by=self.make_task(assigned_to=REP),
		)
		self.assertEqual(out["items"][0]["status"], "Done")

	def test_propose_week_keeps_a_meeting_a_meeting(self):
		"""ACTIVITY_TO_ACTION maps Meeting to create_task, so the round trip
		Meeting -> suggestion -> proposed week used to come back as a Task --
		and the matcher then hunted a CRM Task for the meeting the rep actually
		held, docking adherence through no fault of theirs."""
		self.make_suggestion(
			REP,
			title="Overdue plan item: Meet Plan API Org",
			action_payload={"title": "Meet Plan API Org", "activity_type": "Meeting"},
		)
		frappe.set_user(REP)
		drafts = propose_week(self.monday)
		self.assertEqual(drafts[0]["activity_type"], "Meeting")

	def test_an_in_tree_team_lead_sees_their_own_teams_plans(self):
		frappe.set_user(REP)
		save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		frappe.set_user("Administrator")
		self.make_hierarchy(LEAD, REP)

		frappe.set_user(LEAD)
		self.assertEqual(len(get_plan(self.monday, user=REP)["items"]), 1)
		self.assertEqual(get_visible_reps(), sorted([LEAD, REP]))

	def test_an_in_tree_lead_cannot_see_outside_their_team(self):
		frappe.set_user(OTHER)
		save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		frappe.set_user("Administrator")
		self.make_hierarchy(LEAD, REP)

		frappe.set_user(LEAD)
		with self.assertRaises(frappe.PermissionError):
			get_plan(self.monday, user=OTHER)

	def test_the_generic_document_api_scopes_plans_to_the_same_subtree(self):
		frappe.set_user(OTHER)
		save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		frappe.set_user(REP)
		save_plan(self.monday, [{"activity_type": "Task", "planned_date": self.monday}])
		frappe.set_user("Administrator")
		self.make_hierarchy(LEAD, REP)

		frappe.set_user(LEAD)
		# get_all ignores permissions by design; get_list is the door a rep has
		visible = frappe.get_list("CRM Rep Plan", filters={"user": ("in", USERS)}, pluck="user")
		self.assertEqual(sorted(visible), [REP])

	def test_one_plan_per_rep_week_is_enforced_by_the_database(self):
		frappe.set_user(REP)
		save_plan(self.monday, [{"activity_type": "Call", "planned_date": self.monday}])
		duplicate = frappe.new_doc("CRM Rep Plan", user=REP, week_start=self.monday)
		# the read-then-throw in validate() is exactly what two concurrent saves
		# slip past, so the constraint has to hold without it
		duplicate.flags.ignore_validate = True
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			duplicate.insert(ignore_permissions=True)


from datetime import datetime, timedelta

from crm.install import ensure_visit_event_category


def _this_monday() -> str:
	today = frappe.utils.getdate()
	return str(today - timedelta(days=today.weekday()))


class MarkFulfilledByKindTest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_visit_event_category()

	def setUp(self):
		super().setUp()
		make_sales_user(REP, "Plan Rep")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(REP)

	def tearDown(self):
		frappe.db.rollback()

	def _plan_with(self, activity_type: str) -> str:
		plan = save_plan(_this_monday(), [{"activity_type": activity_type, "planned_date": _this_monday()}])
		return plan["items"][0]["name"]

	def _event(self, category=None):
		fields = {
			"doctype": "Event",
			"subject": "x",
			"starts_on": datetime.now(),
			"event_type": "Private",
		}
		if category:
			fields["event_category"] = category
		return frappe.get_doc(fields).insert()

	def test_a_visit_item_accepts_a_visit_event_and_refuses_a_plain_one(self):
		item = self._plan_with("Visit")
		plain = self._event()
		with self.assertRaises(frappe.ValidationError):
			mark_fulfilled(item, "Event", plain.name)
		visit = self._event("Visit")
		plan = mark_fulfilled(item, "Event", visit.name)
		self.assertEqual(plan["items"][0]["status"], "Done")

	def test_a_meeting_item_still_accepts_a_plain_event(self):
		item = self._plan_with("Meeting")
		plan = mark_fulfilled(item, "Event", self._event().name)
		self.assertEqual(plan["items"][0]["status"], "Done")


from crm.api.rep_plan import log_unplanned_visit


class UnplannedVisitTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		make_sales_user(REP, "Plan Rep")
		self.org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "4D Union Section"}
		).insert()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(REP)

	def tearDown(self):
		frappe.db.rollback()

	def test_logs_a_done_visit_the_matcher_will_leave_alone(self):
		plan = log_unplanned_visit(self.org.name, "Called to site for a breakdown on the 200mm valve")
		item = plan["items"][0]
		self.assertEqual(item["activity_type"], "Visit")
		self.assertEqual(item["status"], "Done")
		self.assertEqual(item["manual_override"], 1)
		self.assertEqual(item["fulfilled_by_doctype"], "Event")
		event = frappe.get_doc("Event", item["fulfilled_by"])
		self.assertEqual(event.event_category, "Visit")
		self.assertEqual(event.status, "Completed")
		self.assertEqual(event.owner, REP)
		self.assertIn(self.org.name, [p.reference_docname for p in event.event_participants])

	def test_a_note_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			log_unplanned_visit(self.org.name, "   ")

	def test_an_unknown_organization_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			log_unplanned_visit("Nobody Ltd", "x")

	def test_lands_in_the_week_of_the_visit_not_today(self):
		when = frappe.utils.get_datetime(_this_monday()) - timedelta(days=7)
		plan = log_unplanned_visit(self.org.name, "last week", when=str(when))
		self.assertEqual(plan["week_start"], str(when.date()))
