# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The command palette finds what its user may open, and nothing else."""

import json
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, now_datetime, nowdate

from crm.api.command_palette import MAX_QUERY_LENGTH, SEARCH_LIMIT, UPCOMING_LIMIT, search
from crm.tests.test_row_permissions import ensure_rep

ALICE = "palette-alice@crmtest.test"
BOB = "palette-bob@crmtest.test"
OUTSIDER = "palette-outsider@crmtest.test"


def make_org(organization_name, **kwargs):
	return (
		frappe.get_doc({"doctype": "CRM Organization", "organization_name": organization_name, **kwargs})
		.insert(ignore_if_duplicate=True)
		.name
	)


def make_deal(owner, organization, quote=None):
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": organization,
				"deal_owner": owner,
				"acumatica_sales_quote": quote,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_lead(owner, first_name, **kwargs):
	return (
		frappe.get_doc({"doctype": "CRM Lead", "first_name": first_name, "lead_owner": owner, **kwargs})
		.insert(ignore_permissions=True)
		.name
	)


def make_task(owner, title, due_date, status="Todo"):
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": title,
				"assigned_to": owner,
				"due_date": due_date,
				"status": status,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def plan_visit(user, organization, planned_date, status="Planned"):
	day = getdate(planned_date)
	frappe.get_doc(
		{
			"doctype": "CRM Rep Plan",
			"user": user,
			"week_start": day - timedelta(days=day.weekday()),
			"items": [
				{
					"activity_type": "Visit",
					"planned_date": day,
					"organization": organization,
					"status": status,
				}
			],
		}
	).insert(ignore_permissions=True)


class CommandPaletteTest(IntegrationTestCase):
	def setUp(self):
		ensure_rep(ALICE, "Alice")
		ensure_rep(BOB, "Bob")
		frappe.db.delete("CRM Rep Plan", {"user": ("in", [ALICE, BOB])})
		frappe.db.delete("CRM Task", {"assigned_to": ("in", [ALICE, BOB])})
		self.org = make_org("Palette Valves", acumatica_id="C-PAL001")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()


class TestSearch(CommandPaletteTest):
	def matches(self, query):
		return search(query)["matches"]

	def test_a_deal_is_found_by_its_quote_number(self):
		deal = make_deal(ALICE, self.org, "QT900111")
		frappe.set_user(ALICE)

		[match] = self.matches("QT900111")

		self.assertEqual((match["doctype"], match["name"], match["route"]), ("CRM Deal", deal, "Deal"))
		self.assertEqual(match["title"], "Palette Valves")
		self.assertEqual(match["detail"], "QT900111")

	def test_a_customer_is_found_by_its_acumatica_id(self):
		frappe.set_user(ALICE)

		[match] = self.matches("C-PAL001")

		self.assertEqual(match["doctype"], "CRM Organization")
		self.assertEqual(match["title"], "Palette Valves")
		self.assertEqual(match["route"], "Organization")

	def test_a_contact_is_found_by_email(self):
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Palette",
				"last_name": "Person",
				"email_ids": [{"email_id": "palette.person@example.com", "is_primary": 1}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(ALICE)

		[match] = self.matches("palette.person@example.com")

		self.assertEqual((match["doctype"], match["name"]), ("Contact", contact.name))

	def test_a_contact_is_found_by_its_acumatica_id(self):
		contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": "Palette", "last_name": "Linked", "acumatica_id": "PAL-CT-1"}
		).insert(ignore_permissions=True)
		frappe.set_user(ALICE)

		[match] = self.matches("PAL-CT-1")

		self.assertEqual((match["doctype"], match["name"]), ("Contact", contact.name))

	def test_a_doctype_the_user_cannot_read_is_left_out(self):
		frappe.get_doc({"doctype": "Contact", "first_name": "Unreadable", "last_name": "Palette"}).insert(
			ignore_permissions=True
		)
		frappe.set_user(ALICE)

		with patch(
			"crm.api.command_palette.frappe.has_permission",
			side_effect=lambda doctype, *args, **kwargs: doctype != "Contact",
		):
			self.assertEqual(self.matches("Unreadable"), [])

	def test_a_lead_is_found_by_phone(self):
		lead = make_lead(ALICE, "Phoned", mobile_no="+27825550111")
		frappe.set_user(ALICE)

		[match] = self.matches("825550111")

		self.assertEqual((match["doctype"], match["name"]), ("CRM Lead", lead))

	def test_matched_values_come_back_for_the_client_to_rank_on(self):
		make_deal(ALICE, self.org, "QT900111")
		frappe.set_user(ALICE)

		[match] = self.matches("QT900111")

		self.assertIn("QT900111", match["keywords"])

	def test_a_rep_does_not_find_another_reps_deal(self):
		make_deal(BOB, self.org, "QT900222")
		frappe.set_user(ALICE)

		self.assertEqual(self.matches("QT900222"), [])

	def test_a_rep_does_not_find_another_reps_lead(self):
		make_lead(BOB, "Bobshidden", mobile_no="+27825550222")
		frappe.set_user(ALICE)

		self.assertEqual(self.matches("Bobshidden"), [])
		self.assertEqual(self.matches("825550222"), [])

	def test_each_doctype_returns_a_handful(self):
		for index in range(SEARCH_LIMIT + 2):
			make_lead(ALICE, f"Numerous{index}")
		frappe.set_user(ALICE)

		self.assertEqual(len(self.matches("Numerous")), SEARCH_LIMIT)

	def test_one_character_searches_nothing(self):
		make_lead(ALICE, "Q")
		frappe.set_user(ALICE)

		self.assertEqual(self.matches("Q"), [])

	def test_an_overlong_query_is_cut(self):
		frappe.set_user(ALICE)

		with patch("crm.api.command_palette.frappe.get_list", wraps=frappe.get_list) as get_list:
			self.matches("x" * (MAX_QUERY_LENGTH + 500))

		pattern = get_list.call_args.kwargs["or_filters"][0][2]
		self.assertEqual(len(pattern), MAX_QUERY_LENGTH + len("%%"))

	def test_a_user_with_no_crm_role_is_refused(self):
		if not frappe.db.exists("User", OUTSIDER):
			frappe.get_doc(
				{"doctype": "User", "email": OUTSIDER, "first_name": "Outsider", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(OUTSIDER)

		with self.assertRaises(frappe.PermissionError):
			search("Palette")

	def test_a_manager_outside_the_hierarchy_on_own_records_finds_only_their_own(self):
		manager = "palette-manager@crmtest.test"
		if not frappe.db.exists("User", manager):
			frappe.get_doc(
				{"doctype": "User", "email": manager, "first_name": "Manager", "send_welcome_email": 0}
			).insert(ignore_permissions=True).add_roles("Sales Manager")
		make_deal(BOB, self.org, "QT900333")
		mine = make_deal(manager, self.org, "QT900444")
		for field, value in (
			("enable_sales_hierarchy", 1),
			("manager_outside_hierarchy", "Own records only"),
		):
			doctype = "FCRM Settings" if field == "enable_sales_hierarchy" else "CRM Access Settings"
			saved = frappe.db.get_single_value(doctype, field)
			frappe.db.set_single_value(doctype, field, value)
			self.addCleanup(frappe.db.set_single_value, doctype, field, saved)
		frappe.clear_cache()
		frappe.set_user(manager)

		self.assertEqual(self.matches("QT900333"), [])
		self.assertEqual([match["name"] for match in self.matches("QT900444")], [mine])


class TestRecent(CommandPaletteTest):
	def recent(self, names):
		return search(recent_names=json.dumps(names))["recent"]

	def test_recent_records_keep_the_order_they_were_sent_in(self):
		first, second = make_lead(ALICE, "First"), make_lead(ALICE, "Second")
		frappe.set_user(ALICE)

		recent = self.recent({"CRM Lead": [second, first]})

		self.assertEqual([record["name"] for record in recent], [second, first])

	def test_a_record_the_rep_cannot_read_is_dropped(self):
		mine, hidden = make_lead(ALICE, "Mine"), make_lead(BOB, "Hidden")
		frappe.set_user(ALICE)

		recent = self.recent({"CRM Lead": [hidden, mine]})

		self.assertEqual([record["name"] for record in recent], [mine])

	def test_a_doctype_the_palette_does_not_search_is_ignored(self):
		frappe.set_user(ALICE)

		self.assertEqual(self.recent({"User": ["Administrator"]}), [])

	def test_the_number_of_names_is_bounded(self):
		leads = [make_lead(ALICE, f"Recent{index}") for index in range(SEARCH_LIMIT + 2)]
		frappe.set_user(ALICE)

		self.assertEqual(len(self.recent({"CRM Lead": leads})), SEARCH_LIMIT)

	def test_a_malformed_payload_is_ignored(self):
		frappe.set_user(ALICE)

		self.assertEqual(search(recent_names="not-json")["recent"], [])
		self.assertEqual(search(recent_names="[1, 2]")["recent"], [])
		self.assertEqual(self.recent({"CRM Lead": [{"nested": "object"}]}), [])

	def test_nothing_recent_is_returned_while_searching(self):
		lead = make_lead(ALICE, "Searching")
		frappe.set_user(ALICE)

		self.assertEqual(search("Searching", json.dumps({"CRM Lead": [lead]}))["recent"], [])


class TestUpcoming(CommandPaletteTest):
	def upcoming(self):
		return search()["upcoming"]

	def test_a_task_due_soon_is_upcoming(self):
		task = make_task(ALICE, "Call the plant", add_days(now_datetime(), 1))
		frappe.set_user(ALICE)

		[item] = self.upcoming()

		self.assertEqual((item["kind"], item["name"], item["title"]), ("task", task, "Call the plant"))
		self.assertEqual(item["route"], "Tasks")

	def test_a_task_on_a_lead_opens_the_lead(self):
		lead = make_lead(ALICE, "Tasked")
		task = frappe.get_doc("CRM Task", make_task(ALICE, "On the lead", add_days(now_datetime(), 1)))
		task.update({"reference_doctype": "CRM Lead", "reference_docname": lead})
		task.save(ignore_permissions=True)
		frappe.set_user(ALICE)

		[item] = self.upcoming()

		self.assertEqual((item["route"], item["route_name"]), ("Lead", lead))

	def test_a_task_on_a_record_the_rep_cannot_read_opens_the_task_list(self):
		hidden = make_lead(BOB, "Hiddenparent")
		task = frappe.get_doc("CRM Task", make_task(ALICE, "On a hidden lead", add_days(now_datetime(), 1)))
		task.update({"reference_doctype": "CRM Lead", "reference_docname": hidden})
		task.save(ignore_permissions=True)
		frappe.set_user(ALICE)

		[item] = self.upcoming()

		self.assertEqual((item["route"], item["route_name"]), ("Tasks", None))

	def test_a_task_whose_record_was_deleted_opens_the_task_list(self):
		task = make_task(ALICE, "Dangling", add_days(now_datetime(), 1))
		frappe.db.set_value(
			"CRM Task", task, {"reference_doctype": "CRM Lead", "reference_docname": "CRM-LEAD-NO-SUCH"}
		)
		frappe.set_user(ALICE)

		[item] = self.upcoming()

		self.assertEqual((item["route"], item["route_name"]), ("Tasks", None))

	def test_a_finished_task_is_not_upcoming(self):
		make_task(ALICE, "Finished", add_days(now_datetime(), 1), status="Done")
		make_task(ALICE, "Abandoned", add_days(now_datetime(), 1), status="Canceled")
		frappe.set_user(ALICE)

		self.assertEqual(self.upcoming(), [])

	def test_another_reps_task_is_not_upcoming(self):
		make_task(BOB, "Bobs task", add_days(now_datetime(), 1))
		frappe.set_user(ALICE)

		self.assertEqual(self.upcoming(), [])

	def test_someone_who_can_read_the_teams_tasks_still_sees_only_their_own(self):
		make_task(BOB, "Bobs task", add_days(now_datetime(), 1))

		titles = [item["title"] for item in self.upcoming()]

		self.assertNotIn("Bobs task", titles)

	def test_a_recently_overdue_task_stays_upcoming(self):
		make_task(ALICE, "Slipped", add_days(now_datetime(), -2))
		frappe.set_user(ALICE)

		self.assertEqual([item["title"] for item in self.upcoming()], ["Slipped"])

	def test_a_task_past_the_grace_period_is_backlog_not_upcoming(self):
		make_task(ALICE, "Slipped long ago", add_days(now_datetime(), -4))
		frappe.set_user(ALICE)

		self.assertEqual(self.upcoming(), [])

	def test_a_task_due_within_the_week_is_upcoming(self):
		make_task(ALICE, "Next week", add_days(now_datetime(), 6))
		frappe.set_user(ALICE)

		self.assertEqual([item["title"] for item in self.upcoming()], ["Next week"])

	def test_a_task_due_beyond_the_week_is_not_upcoming(self):
		make_task(ALICE, "Far off", add_days(now_datetime(), 8))
		frappe.set_user(ALICE)

		self.assertEqual(self.upcoming(), [])

	def test_overdue_tasks_do_not_hide_todays_visit(self):
		for index in range(UPCOMING_LIMIT + 1):
			make_task(ALICE, f"Late {index}", add_days(now_datetime(), -1))
		plan_visit(ALICE, self.org, nowdate())
		frappe.set_user(ALICE)

		upcoming = self.upcoming()

		self.assertEqual(upcoming[0]["kind"], "plan")
		self.assertEqual(sum(item["kind"] == "task" for item in upcoming), UPCOMING_LIMIT)

	def test_todays_planned_visit_is_upcoming(self):
		plan_visit(ALICE, self.org, "2026-03-04")
		frappe.set_user(ALICE)

		with patch("crm.api.command_palette.nowdate", return_value="2026-03-04"):
			[item] = self.upcoming()

		self.assertEqual((item["kind"], item["title"]), ("plan", "Palette Valves"))
		self.assertEqual((item["route"], item["label"]), ("Planner", "Visit"))
		self.assertEqual(item["when"], "Today")

	def test_tomorrows_planned_visit_is_upcoming(self):
		plan_visit(ALICE, self.org, "2026-03-04")
		frappe.set_user(ALICE)

		with patch("crm.api.command_palette.nowdate", return_value="2026-03-03"):
			[item] = self.upcoming()

		self.assertEqual(item["when"], "Tomorrow")

	def test_a_visit_the_day_after_tomorrow_is_not_upcoming(self):
		plan_visit(ALICE, self.org, add_days(nowdate(), 2))
		frappe.set_user(ALICE)

		self.assertEqual(self.upcoming(), [])

	def test_a_visit_next_week_is_not_upcoming(self):
		plan_visit(ALICE, self.org, add_days(nowdate(), 7))
		frappe.set_user(ALICE)

		self.assertEqual(self.upcoming(), [])

	def test_another_reps_visit_is_not_upcoming(self):
		plan_visit(BOB, self.org, nowdate())
		frappe.set_user(ALICE)

		self.assertEqual(self.upcoming(), [])

	def test_a_completed_visit_is_not_upcoming(self):
		plan_visit(ALICE, self.org, nowdate(), status="Done")
		frappe.set_user(ALICE)

		self.assertEqual(self.upcoming(), [])

	def test_nothing_upcoming_is_returned_while_searching(self):
		make_task(ALICE, "Call the plant", add_days(now_datetime(), 1))
		frappe.set_user(ALICE)

		self.assertEqual(search("Call the plant")["upcoming"], [])
