# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Kanban cards say how much activity a record has, and asking costs no query per card."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.doc import get_data, set_activity_counts
from crm.tests.test_row_permissions import ensure_rep

ALICE = "kanban-alice@crmtest.test"
BOB = "kanban-bob@crmtest.test"


def make_lead(first_name, owner=None, **kwargs):
	return frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": first_name,
			"last_name": "Kanban",
			"lead_owner": owner,
			**kwargs,
		}
	).insert(ignore_permissions=True)


def add_email(lead, communication_type="Communication"):
	frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": communication_type,
			"communication_medium": "Email",
			"subject": "Hello",
			"reference_doctype": "CRM Lead",
			"reference_name": lead.name,
		}
	).insert(ignore_permissions=True)


def add_comment(lead, comment_type="Comment"):
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": comment_type,
			"content": "Spoke to them",
			"reference_doctype": "CRM Lead",
			"reference_name": lead.name,
		}
	).insert(ignore_permissions=True)


def add_task(lead):
	frappe.get_doc(
		{
			"doctype": "CRM Task",
			"title": "Follow up",
			"reference_doctype": "CRM Lead",
			"reference_docname": lead.name,
		}
	).insert(ignore_permissions=True)


def add_note(lead):
	frappe.get_doc(
		{
			"doctype": "FCRM Note",
			"title": "Site visit",
			"reference_doctype": "CRM Lead",
			"reference_docname": lead.name,
		}
	).insert(ignore_permissions=True)


class TestKanbanActivityCounts(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def counts_for(self, lead):
		[row] = set_activity_counts([{"name": lead.name}], "CRM Lead")
		return {key: row[key] for key in ("_email_count", "_note_count", "_task_count", "_comment_count")}

	def test_each_card_counts_its_own_activity(self):
		busy, other = make_lead("Busy"), make_lead("Other")
		add_email(busy)
		add_note(busy)
		add_note(busy)
		add_task(busy)
		add_comment(busy)
		add_comment(busy)
		add_comment(busy)
		add_task(other)

		self.assertEqual(
			self.counts_for(busy),
			{"_email_count": 1, "_note_count": 2, "_task_count": 1, "_comment_count": 3},
		)
		self.assertEqual(
			self.counts_for(other),
			{"_email_count": 0, "_note_count": 0, "_task_count": 1, "_comment_count": 0},
		)

	def test_an_automated_message_counts_as_an_email(self):
		lead = make_lead("Automated")
		add_email(lead, "Automated Message")

		self.assertEqual(self.counts_for(lead)["_email_count"], 1)

	def test_a_system_comment_is_not_counted(self):
		lead = make_lead("System")
		add_comment(lead, "Info")

		self.assertEqual(self.counts_for(lead)["_comment_count"], 0)

	def test_no_cards_runs_no_queries(self):
		with self.assertQueryCount(0):
			self.assertEqual(set_activity_counts([], "CRM Lead"), [])

	def test_more_cards_do_not_mean_more_queries(self):
		rows = [{"name": make_lead(f"Card {index}").name} for index in range(3)]
		set_activity_counts(rows, "CRM Lead")

		with self.assertQueryCount(5):
			set_activity_counts(rows, "CRM Lead")

	def test_kanban_columns_carry_the_counts(self):
		lead = make_lead("Column")
		add_comment(lead)

		result = get_data(
			"CRM Lead",
			{"name": lead.name},
			"modified desc",
			column_field="status",
			title_field="lead_name",
			rows=["name", "lead_name", "status"],
			kanban_columns=[{"name": lead.status}],
			kanban_fields=["lead_name"],
			view={"view_type": "kanban"},
		)

		[card] = result["data"][0]["data"]
		self.assertEqual(card["_comment_count"], 1)
		self.assertEqual(card["_email_count"], 0)

	def kanban(self, doctype="CRM Lead", filters=None, rows=None, name="New", title="lead_name"):
		# The title field goes into the query, so naming "name" here would select the
		# real column over any alias in `rows`.
		return get_data(
			doctype,
			filters or {},
			"modified desc",
			column_field="status",
			title_field=title,
			rows=rows or ["name", "status"],
			kanban_columns=[{"name": name}],
			kanban_fields=[title],
			view={"view_type": "kanban"},
		)

	def test_a_rep_reads_no_counts_for_a_record_they_cannot_read(self):
		ensure_rep(ALICE, "Alice")
		ensure_rep(BOB, "Bob")
		hidden = make_lead("Hidden", BOB)
		add_comment(hidden)
		add_note(hidden)
		frappe.set_user(ALICE)

		[row] = set_activity_counts([{"name": hidden.name}], "CRM Lead")

		self.assertEqual(row["_comment_count"], 0)
		self.assertEqual(row["_note_count"], 0)

	def test_aliasing_a_hidden_name_onto_a_readable_row_reveals_nothing(self):
		ensure_rep(ALICE, "Alice")
		ensure_rep(BOB, "Bob")
		hidden = make_lead("Hidden", BOB)
		add_comment(hidden)
		mine = make_lead("Mine", ALICE, job_title=hidden.name)
		frappe.set_user(ALICE)

		for rows in (
			["job_title as name", "status"],
			[{"CONCAT": f"'{hidden.name}'", "as": "name"}, "status"],
		):
			result = self.kanban(filters={"name": mine.name}, rows=rows, name=mine.status)

			[card] = result["data"][0]["data"]
			self.assertEqual(card["name"], hidden.name)
			self.assertEqual(card["_comment_count"], 0)

	def test_a_board_that_is_not_leads_or_deals_is_not_counted(self):
		frappe.get_doc({"doctype": "CRM Task", "title": "On the board", "status": "Todo"}).insert(
			ignore_permissions=True
		)

		result = self.kanban("CRM Task", name="Todo", title="title")

		[card, *_] = result["data"][0]["data"]
		self.assertNotIn("_comment_count", card)
