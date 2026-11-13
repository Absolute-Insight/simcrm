# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Kanban cards say how much activity a record has, and asking costs no query per card."""

from contextlib import contextmanager
from unittest.mock import patch

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


@contextmanager
def counted_queries():
	"""The SQL statements run inside the block, as assertQueryCount collects them."""
	queries = []
	original = frappe.db.__class__.sql

	def sql(*args, **kwargs):
		result = original(*args, **kwargs)
		queries.append(str(args[0].last_query))
		return result

	frappe.db.__class__.sql = sql
	try:
		yield queries
	finally:
		frappe.db.__class__.sql = original


COUNT_KEYS = ("_email_count", "_note_count", "_task_count", "_comment_count")


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


class TestKanbanBoardCountsAreBatched(IntegrationTestCase):
	"""The counts were read column by column: five queries for each stage of the
	board. They are read once for the whole board, and nothing a card shows moved.
	"""

	def setUp(self):
		ensure_rep(ALICE, "Alice")
		ensure_rep(BOB, "Bob")
		frappe.set_user("Administrator")
		# a lost lead wants a reason to save; the other stages are board enough
		self.statuses = frappe.get_all(
			"CRM Lead Status", filters={"type": ("!=", "Lost")}, pluck="name", order_by="position asc"
		)
		self.assertGreaterEqual(len(self.statuses), 4)
		self.marker = f"Batch {frappe.generate_hash(length=8)}"
		# Alice's and Bob's leads in every column, each with its own mix of activity
		for index, status in enumerate(self.statuses):
			for owner in (ALICE, BOB):
				lead = make_lead(owner.split("@")[0], owner, status=status, job_title=self.marker)
				for _ in range(index % 3):
					add_comment(lead)
				for _ in range((index + 1) % 2):
					add_note(lead)
				if owner == ALICE:
					add_task(lead)
					add_email(lead)
			# and a second card of Alice's, so a column holds more than one
			add_comment(make_lead("second", ALICE, status=status, job_title=self.marker))

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def board(self, statuses=None, **kwargs):
		return get_data(
			"CRM Lead",
			{"job_title": self.marker},
			"modified desc",
			column_field="status",
			title_field="lead_name",
			rows=["name", "lead_name", "status"],
			kanban_columns=[{"name": status} for status in statuses or self.statuses],
			kanban_fields=["lead_name"],
			view={"view_type": "kanban"},
			**kwargs,
		)

	def test_a_board_shows_what_counting_each_column_alone_showed(self):
		for user, cards_per_column in ((ALICE, 2), ("Administrator", 3)):
			frappe.set_user(user)
			result = self.board()

			self.assertEqual([column["column"]["name"] for column in result["data"]], self.statuses)
			for column in result["data"]:
				cards = column["data"]
				self.assertEqual(len(cards), cards_per_column, (user, column["column"]["name"]))
				self.assertEqual(column["column"]["all_count"], cards_per_column)
				# the old code: this column's cards, counted on their own
				alone = set_activity_counts([{"name": card["name"]} for card in cards], "CRM Lead")
				for card, expected in zip(cards, alone, strict=True):
					self.assertEqual(
						{key: card[key] for key in COUNT_KEYS},
						{key: expected[key] for key in COUNT_KEYS},
						(user, card["name"]),
					)
			# and the board is not all zeroes
			totals = [
				sum(card[key] for column in result["data"] for card in column["data"]) for key in COUNT_KEYS
			]
			self.assertTrue(all(totals), totals)

	def test_a_capped_column_page_is_still_counted_card_by_card(self):
		frappe.set_user("Administrator")
		result = get_data(
			"CRM Lead",
			{"job_title": self.marker},
			"modified desc",
			column_field="status",
			title_field="lead_name",
			rows=["name", "lead_name", "status"],
			kanban_columns=[{"name": status, "page_length": 1} for status in self.statuses],
			kanban_fields=["lead_name"],
			view={"view_type": "kanban"},
		)

		for column in result["data"]:
			[card] = column["data"]
			self.assertEqual(column["column"]["all_count"], 3)
			[expected] = set_activity_counts([{"name": card["name"]}], "CRM Lead")
			self.assertEqual(card["_comment_count"], expected["_comment_count"])

	def test_the_counts_are_read_once_for_the_board(self):
		frappe.set_user(ALICE)
		with patch("crm.api.doc.set_activity_counts", wraps=set_activity_counts) as counts:
			self.board()

		self.assertEqual(counts.call_count, 1)

	def test_another_column_costs_its_page_and_nothing_else(self):
		frappe.set_user(ALICE)
		self.board()  # warm the caches both runs below then share

		with counted_queries() as narrow:
			self.board(self.statuses[:2])
		with counted_queries() as wide:
			self.board()

		# A rep's page read is three statements: the two row-scope lookups frappe
		# and the hierarchy make, and the page. It was ten a column: that, the
		# same again to re-read the names, and the four counts.
		extra_columns = len(self.statuses) - 2
		self.assertLessEqual(
			len(wide) - len(narrow), 3 * extra_columns, msg="Queries executed: \n" + "\n\n".join(wide)
		)
		activity = [
			query
			for query in wide
			if any(
				f"`tab{table}`" in query.split("where")[0].split("WHERE")[0]
				for table in ("Communication", "Comment", "CRM Task", "FCRM Note")
			)
		]
		self.assertEqual(len(activity), 4, msg="\n\n".join(activity))
