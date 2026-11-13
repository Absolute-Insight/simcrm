# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Replaying a phone's outbox: once, as the rep, and inside the rules.

The phone sends an entry until it hears back, so the same entry arriving twice
is the normal case, not an edge. And the entry carries a time the server did
not witness, so what that time is allowed to buy is the other half.
"""

from __future__ import annotations

import time
from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.offline import LATE_AFTER_SECONDS, OFFLINE_GRACE_HOURS, get_pack, replay
from crm.api.rep_plan import get_plan, log_unplanned_visit, save_plan
from crm.fcrm.doctype.crm_offline_receipt.crm_offline_receipt import RECEIPT_DAYS, purge_old_receipts
from crm.install import ensure_visit_event_category

REP = "replay-rep@crmtest.test"
OTHER = "replay-other@crmtest.test"


def make_user(email: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


def new_id() -> str:
	return frappe.generate_hash(length=32)


def ago(**delta) -> int:
	"""A device timestamp (ms) that far in the past."""
	return int((time.time() - timedelta(**delta).total_seconds()) * 1000)


def this_monday() -> str:
	today = frappe.utils.getdate()
	return str(today - timedelta(days=today.weekday()))


class ReplayTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_visit_event_category()
		make_user(REP)
		make_user(OTHER)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 0)
		frappe.db.set_single_value("FCRM Settings", "lock_past_plans", 0)
		frappe.db.set_single_value("CRM Access Settings", "rep_customer_scope", "Own and unclaimed customers")
		self.org = self.make_org(REP)
		self.foreign = self.make_org(OTHER)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(REP)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def make_org(self, owner: str) -> str:
		doc = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": f"Replay {frappe.generate_hash(length=6)}"}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", doc.name, "account_owner", owner)
		return doc.name

	def visit(self, **overrides) -> dict:
		return {
			"activity_type": "Visit",
			"organization": self.org,
			"note": "Checked the gate valves",
		} | overrides

	def items(self, week: str | None = None) -> list[dict]:
		return get_plan(week or this_monday())["items"]

	def plan_one(self, activity_type: str = "Visit") -> str:
		plan = save_plan(
			this_monday(),
			[
				{
					"activity_type": activity_type,
					"planned_date": str(frappe.utils.getdate()),
					"organization": self.org,
				}
			],
		)
		return plan["items"][0]["name"]


class ExactlyOnceTest(ReplayTestCase):
	def test_an_entry_is_applied(self):
		out = replay(new_id(), "log_activity", self.visit())
		self.assertEqual(out["status"], "applied")
		self.assertEqual([row["status"] for row in self.items()], ["Done"])

	def test_the_same_entry_sent_again_changes_nothing(self):
		request_id = new_id()
		replay(request_id, "log_activity", self.visit())
		again = replay(request_id, "log_activity", self.visit())
		self.assertEqual(again["status"], "duplicate")
		self.assertEqual(len(self.items()), 1)
		self.assertEqual(frappe.db.count("Event", {"owner": REP, "event_category": "Visit"}), 1)

	def test_a_refused_entry_leaves_no_receipt_and_can_be_sent_again(self):
		request_id = new_id()
		with self.assertRaises(frappe.ValidationError):
			replay(request_id, "log_activity", self.visit(note="  "))
		# the request ends in a rollback when the handler throws; a test has to say so
		frappe.db.rollback()
		frappe.set_user(REP)
		self.assertFalse(frappe.db.exists("CRM Offline Receipt", request_id))

	def test_another_users_id_is_neither_applied_nor_called_a_duplicate(self):
		request_id = new_id()
		replay(request_id, "log_activity", self.visit())
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.ValidationError):
			replay(request_id, "log_activity", {"activity_type": "Admin", "note": "Mine"})

	def test_an_activity_at_another_reps_customer_is_refused_and_leaves_nothing(self):
		request_id = new_id()
		with self.assertRaises(frappe.PermissionError):
			replay(request_id, "log_activity", self.visit(organization=self.foreign))
		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("CRM Offline Receipt", request_id))
		self.assertFalse(frappe.db.count("Event", {"owner": REP, "event_category": "Visit"}))

	def test_a_rep_cannot_read_receipts(self):
		replay(new_id(), "log_activity", self.visit())
		self.assertFalse(frappe.has_permission("CRM Offline Receipt", "read"))
		self.assertFalse(frappe.has_permission("CRM Offline Receipt", "create"))

	def test_a_payload_nested_past_reading_is_refused_not_a_crash(self):
		with self.assertRaises(frappe.ValidationError):
			replay(new_id(), "log_activity", "[" * 5000)

	def test_the_copy_that_loses_the_race_is_told_duplicate(self):
		# Two copies at once: both pass the first look, one insert wins. The
		# loser's second look has to see the winner's row, and its owner.
		from unittest.mock import patch

		from crm.api import offline

		request_id = new_id()
		replay(request_id, "log_activity", self.visit())
		real = offline._already_applied
		looks = []

		def first_look_misses(rid, current=False):
			looks.append(current)
			return False if len(looks) == 1 else real(rid, current)

		with patch.object(offline, "_already_applied", side_effect=first_look_misses):
			out = replay(request_id, "log_activity", self.visit())
		self.assertEqual(out["status"], "duplicate")
		self.assertEqual(looks, [False, True])
		self.assertEqual(len(self.items()), 1)

	def test_only_the_listed_actions_exist(self):
		for action in ("frappe.client.delete", "save_plan", "", "get_pack"):
			with self.assertRaises(frappe.ValidationError):
				replay(new_id(), action, {})

	def test_an_id_must_look_like_one(self):
		for request_id in (
			"",
			"short",
			"x" * 80,
			"has spaces in the middle of it",
			"../../etc/passwd-padding",
		):
			with self.assertRaises(frappe.ValidationError):
				replay(request_id, "log_activity", self.visit())

	def test_a_payload_has_a_size(self):
		with self.assertRaises(frappe.ValidationError):
			replay(new_id(), "log_activity", self.visit(note="x" * 30_000))

	def test_old_receipts_are_purged_and_recent_ones_kept(self):
		old, recent = new_id(), new_id()
		replay(old, "log_activity", self.visit())
		replay(recent, "log_activity", self.visit(activity_type="Admin", organization=None))
		frappe.db.set_value(
			"CRM Offline Receipt",
			old,
			"creation",
			frappe.utils.now_datetime() - timedelta(days=RECEIPT_DAYS + 1),
			update_modified=False,
		)
		purge_old_receipts()
		self.assertFalse(frappe.db.exists("CRM Offline Receipt", old))
		self.assertTrue(frappe.db.exists("CRM Offline Receipt", recent))


class CapturedTimeTest(ReplayTestCase):
	def test_an_entry_sent_at_once_is_not_flagged(self):
		out = replay(new_id(), "log_activity", self.visit(), ago(seconds=5))
		self.assertFalse(out["late"])
		self.assertEqual(self.items()[0]["captured_offline"], 0)

	def test_an_entry_that_arrived_late_is_flagged_and_keeps_its_own_time(self):
		captured = ago(hours=3)
		out = replay(new_id(), "log_activity", self.visit(), captured)
		self.assertTrue(out["late"])
		row = next(item for item in get_pack()["history"] if item["organization"] == self.org)
		self.assertEqual(row["captured_offline"], 1)
		event = frappe.get_doc("Event", row["fulfilled_by"])
		self.assertEqual(event.starts_on, self.site_time(captured))

	def site_time(self, captured_ms: int):
		from datetime import UTC, datetime

		moment = frappe.utils.convert_utc_to_system_timezone(
			datetime.fromtimestamp(captured_ms / 1000, tz=UTC)
		)
		return moment.replace(tzinfo=None, microsecond=0)

	def test_a_time_in_the_future_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			replay(new_id(), "log_activity", self.visit(), ago(hours=-2))

	def test_a_clock_a_little_fast_is_brought_back_to_now(self):
		out = replay(new_id(), "log_activity", self.visit(), ago(seconds=-60))
		self.assertEqual(out["status"], "applied")

	def test_rubbish_for_a_time_is_refused(self):
		for rubbish in ("yesterday", "nan", "inf", "-inf", -5):
			with self.assertRaises(frappe.ValidationError):
				replay(new_id(), "log_activity", self.visit(), rubbish)

	def test_the_flag_cannot_be_set_from_the_online_door(self):
		# the whitelisted function takes no such argument: a request cannot pass it
		with self.assertRaises(TypeError):
			log_unplanned_visit(self.org, "Sneaky", None, None, None, "Visit", captured_offline=True)


class PastLockTest(ReplayTestCase):
	"""FCRM Settings -> "plan only for today or later" is on."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.set_single_value("FCRM Settings", "lock_past_plans", 1)
		frappe.set_user(REP)

	def yesterday_ms(self) -> int:
		return ago(hours=26)

	def test_online_yesterday_is_still_refused(self):
		yesterday = frappe.utils.now_datetime() - timedelta(hours=26)
		with self.assertRaises(frappe.ValidationError):
			log_unplanned_visit(self.org, "Late", str(yesterday), None, None, "Visit")

	def test_a_visit_captured_offline_yesterday_is_accepted_and_flagged(self):
		out = replay(new_id(), "log_activity", self.visit(), self.yesterday_ms())
		self.assertEqual(out["status"], "applied")
		row = next(item for item in get_pack()["history"] if item["organization"] == self.org)
		self.assertEqual((row["status"], row["captured_offline"]), ("Done", 1))

	def test_a_visit_that_crossed_midnight_on_its_way_is_not_refused(self):
		# captured at 23:52, delivered at 00:03: eleven minutes old, not "late",
		# and already yesterday -- the day lock used to refuse it for good
		from unittest.mock import patch

		tomorrow = frappe.utils.getdate() + timedelta(days=1)
		with (
			patch(
				"frappe.utils.getdate",
				side_effect=lambda *a: frappe.utils.data.getdate(*a) if a else tomorrow,
			),
			patch("crm.api.rep_plan.MATCH_HORIZON_WEEKS", 520),
		):
			out = replay(new_id(), "log_activity", self.visit(), ago(seconds=30))
		self.assertEqual(out["status"], "applied")
		self.assertFalse(out["late"])
		row = next(item for item in get_pack()["history"] if item["organization"] == self.org)
		# and it is flagged: the server did not witness the day it is dated
		self.assertEqual(row["captured_offline"], 1)

	def test_past_the_grace_the_lock_stands(self):
		with self.assertRaises(frappe.ValidationError):
			replay(new_id(), "log_activity", self.visit(), ago(hours=OFFLINE_GRACE_HOURS + 2))

	def test_with_the_lock_off_an_old_capture_is_only_as_limited_as_online(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("FCRM Settings", "lock_past_plans", 0)
		frappe.set_user(REP)
		out = replay(new_id(), "log_activity", self.visit(), ago(hours=OFFLINE_GRACE_HOURS + 2))
		self.assertEqual(out["status"], "applied")


class PlannedItemTest(ReplayTestCase):
	def test_an_outcome_closes_the_item(self):
		item = self.plan_one()
		replay(new_id(), "complete_item", {"item": item, "outcome": "Replaced the knife gate"})
		row = self.items()[0]
		self.assertEqual((row["status"], row["outcome"]), ("Done", "Replaced the knife gate"))
		self.assertEqual(row["captured_offline"], 0)

	def test_an_outcome_that_arrived_late_is_flagged(self):
		item = self.plan_one()
		replay(
			new_id(),
			"complete_item",
			{"item": item, "outcome": "Done on site"},
			ago(seconds=LATE_AFTER_SECONDS + 60),
		)
		self.assertEqual(self.items()[0]["captured_offline"], 1)

	def test_a_cancellation_needs_its_reason(self):
		item = self.plan_one()
		with self.assertRaises(frappe.ValidationError):
			replay(new_id(), "cancel_item", {"item": item, "reason": ""})

	def test_a_cancellation_is_recorded(self):
		item = self.plan_one()
		replay(new_id(), "cancel_item", {"item": item, "reason": "Plant shut"})
		self.assertEqual(self.items()[0]["status"], "Cancelled")

	def test_another_reps_item_cannot_be_cancelled_either(self):
		item = self.plan_one()
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			replay(new_id(), "cancel_item", {"item": item, "reason": "Not mine"})

	def test_another_reps_item_is_refused(self):
		item = self.plan_one()
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			replay(new_id(), "complete_item", {"item": item, "outcome": "Not mine"})

	def test_an_item_that_is_gone_is_refused_not_fatal(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			replay(new_id(), "complete_item", {"item": "no-such-item", "outcome": "x"})

	def test_handing_it_back_to_the_matcher_clears_the_flag(self):
		from crm.api.rep_plan import clear_override

		item = self.plan_one()
		replay(new_id(), "complete_item", {"item": item, "outcome": "x"}, ago(hours=1))
		clear_override(item)
		self.assertEqual(self.items()[0]["captured_offline"], 0)

	def test_saving_the_week_keeps_the_flag(self):
		item = self.plan_one()
		replay(new_id(), "complete_item", {"item": item, "outcome": "x"}, ago(hours=1))
		plan = get_plan(this_monday())
		save_plan(this_monday(), plan["items"], str(plan["modified"]))
		self.assertEqual(self.items()[0]["captured_offline"], 1)


class NotesAndTasksTest(ReplayTestCase):
	def test_a_note_on_a_customer(self):
		replay(
			new_id(),
			"add_note",
			{
				"reference_doctype": "CRM Organization",
				"reference_docname": self.org,
				"content": "Ask for <b>Thabo</b>\nGate 3",
			},
		)
		note = frappe.get_last_doc("FCRM Note", {"reference_docname": self.org})
		self.assertEqual(note.owner, REP)
		self.assertEqual(note.title, "Ask for <b>Thabo</b>")
		self.assertIn("&lt;b&gt;Thabo", note.content)
		self.assertIn("<br>", note.content)

	def test_a_note_on_a_customer_the_rep_cannot_see_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			replay(
				new_id(),
				"add_note",
				{"reference_doctype": "CRM Organization", "reference_docname": self.foreign, "content": "x"},
			)

	def test_a_note_cannot_be_hung_on_any_doctype(self):
		with self.assertRaises(frappe.PermissionError):
			replay(
				new_id(), "add_note", {"reference_doctype": "User", "reference_docname": REP, "content": "x"}
			)

	def test_missing_and_not_yours_are_the_same_answer(self):
		# two different errors would tell a rep which customer names exist
		for name in (self.foreign, "No Such Customer Anywhere"):
			with self.assertRaises(frappe.PermissionError):
				replay(
					new_id(),
					"add_note",
					{"reference_doctype": "CRM Organization", "reference_docname": name, "content": "x"},
				)
		with self.assertRaises(frappe.PermissionError):
			replay(new_id(), "close_task", {"task": "999999999", "closing_note": "x"})

	def test_a_name_is_text_never_a_filter(self):
		# frappe.db.exists reads a dict as filters, unscoped: a yes/no probe over
		# every rep's tasks if a handler ever passed one through
		frappe.set_user(OTHER)
		replay(new_id(), "create_task", {"title": "Replay secret pricing"})
		frappe.set_user(REP)
		for probe in ({"title": ["like", "Replay secret%"]}, ["like", "%"], {"assigned_to": OTHER}):
			with self.assertRaises(frappe.ValidationError):
				replay(new_id(), "close_task", {"task": probe, "closing_note": "x"})
			with self.assertRaises(frappe.ValidationError):
				replay(new_id(), "complete_item", {"item": probe, "outcome": "x"})
			with self.assertRaises(frappe.ValidationError):
				replay(
					new_id(),
					"add_note",
					{"reference_doctype": "CRM Organization", "reference_docname": probe, "content": "x"},
				)

	def test_a_task_about_a_deal_the_rep_cannot_read_is_refused(self):
		frappe.set_user("Administrator")
		deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.foreign, "deal_owner": OTHER}
		).insert(ignore_permissions=True)
		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			replay(
				new_id(),
				"create_task",
				{"title": "Peek", "reference_doctype": "CRM Deal", "reference_docname": deal.name},
			)

	def test_a_task_is_created_for_the_caller(self):
		replay(new_id(), "create_task", {"title": "Send the quote", "due_date": "2026-12-01"})
		task = frappe.get_last_doc("CRM Task", {"title": "Send the quote"})
		self.assertEqual((task.assigned_to, task.status), (REP, "Todo"))
		self.assertEqual(str(task.due_date), "2026-12-01 09:00:00")

	def test_a_task_cannot_be_assigned_to_someone_else(self):
		replay(new_id(), "create_task", {"title": "Not yours", "assigned_to": OTHER})
		self.assertEqual(frappe.get_last_doc("CRM Task", {"title": "Not yours"}).assigned_to, REP)

	def test_closing_a_task_needs_the_note_and_the_owner(self):
		replay(new_id(), "create_task", {"title": "Close me"})
		name = frappe.get_last_doc("CRM Task", {"title": "Close me"}).name
		with self.assertRaises(frappe.ValidationError):
			replay(new_id(), "close_task", {"task": name, "closing_note": ""})
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			replay(new_id(), "close_task", {"task": name, "closing_note": "Not mine"})
		frappe.set_user(REP)
		replay(new_id(), "close_task", {"task": name, "closing_note": "Sent"})
		self.assertEqual(frappe.db.get_value("CRM Task", name, ["status", "closing_note"]), ("Done", "Sent"))


class PlanOfflineTest(ReplayTestCase):
	def tomorrow(self) -> str:
		return str(frappe.utils.getdate() + timedelta(days=1))

	def planned(self, day: str) -> list[dict]:
		monday = frappe.utils.getdate(day) - timedelta(days=frappe.utils.getdate(day).weekday())
		return [row for row in self.items(str(monday)) if str(row["planned_date"]) == day]

	def test_a_visit_is_added_to_the_week_without_replacing_it(self):
		existing = self.plan_one("Call")
		day = str(frappe.utils.getdate())
		replay(
			new_id(),
			"plan_item",
			{"activity_type": "Visit", "planned_date": day, "organization": self.org, "note": "Quote"},
		)
		rows = self.planned(day)
		self.assertEqual(sorted(row["activity_type"] for row in rows), ["Call", "Visit"])
		# the row that was already there is the same row, not a copy
		self.assertIn(existing, {row["name"] for row in rows})
		self.assertEqual([row["status"] for row in rows], ["Planned", "Planned"])

	def test_what_the_week_already_held_keeps_its_outcome(self):
		done = self.plan_one()
		replay(new_id(), "complete_item", {"item": done, "outcome": "Seen"})
		replay(new_id(), "plan_item", {"activity_type": "Admin", "planned_date": str(frappe.utils.getdate())})
		kept = next(row for row in self.items() if row["name"] == done)
		self.assertEqual((kept["status"], kept["outcome"]), ("Done", "Seen"))

	def test_another_reps_customer_cannot_be_planned(self):
		with self.assertRaises(frappe.PermissionError):
			replay(
				new_id(),
				"plan_item",
				{"activity_type": "Visit", "planned_date": self.tomorrow(), "organization": self.foreign},
			)

	def test_a_day_that_had_passed_when_it_was_planned_is_refused(self):
		yesterday = str(frappe.utils.getdate() - timedelta(days=1))
		with self.assertRaises(frappe.ValidationError):
			replay(new_id(), "plan_item", {"activity_type": "Admin", "planned_date": yesterday})

	def test_an_unplanned_meeting_is_by_definition_not_planned(self):
		for kind in ("Unplanned Meeting", "Nonsense", ""):
			with self.assertRaises(frappe.ValidationError):
				replay(new_id(), "plan_item", {"activity_type": kind, "planned_date": self.tomorrow()})

	def test_the_same_plan_entry_sent_twice_plans_once(self):
		request_id = new_id()
		payload = {"activity_type": "Admin", "planned_date": self.tomorrow(), "note": "Paperwork"}
		replay(request_id, "plan_item", payload)
		replay(request_id, "plan_item", payload)
		self.assertEqual(len(self.planned(self.tomorrow())), 1)


class SheetsInThePackTest(ReplayTestCase):
	def test_the_pack_lists_sheets_by_page_and_nothing_more(self):
		frappe.set_user("Administrator")
		frappe.get_doc(
			{
				"doctype": "CRM Reference Sheet",
				"sheet_key": "replay-test-sheet",
				"title": "Replay flange table",
				"pages": frappe.as_json(
					[{"page": 1, "image": "/private/files/replay-p1.png", "width": 800, "height": 1100}]
				),
			}
		).insert(ignore_permissions=True)
		frappe.set_user(REP)
		sheet = next(row for row in get_pack()["sheets"] if row["name"] == "replay-test-sheet")
		self.assertEqual(sheet["title"], "Replay flange table")
		self.assertEqual(
			sheet["pages"],
			[{"page": 1, "image": "/private/files/replay-p1.png", "width": 800, "height": 1100}],
		)
		self.assertEqual(set(sheet), {"name", "title", "note", "modified", "pages"})
