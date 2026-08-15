# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The upgrade path for sites that raced two plans onto one rep-week.

The property under test is that nothing is lost. An earlier version of this
cleanup lived in ``on_doctype_update``, ran on every migrate, and deleted the
plan with fewer items — on a real site that is somebody's planned week going
missing during an upgrade, with no record of it. These tests pin the replacement:
merge every item onto one plan, keep the matcher's verdicts, and only then drop
the emptied duplicates.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.patches.v1_0.merge_duplicate_rep_plan_weeks import execute as merge_duplicates

REP = "merge-rep@crmtest.test"
OTHER = "merge-other@crmtest.test"
INDEX = "unique_user_week"


def index_exists() -> bool:
	return bool(
		frappe.db.sql(
			"""select 1 from information_schema.TABLE_CONSTRAINTS
			where table_schema = database() and table_name = %s
			and constraint_type = 'UNIQUE' and constraint_name = %s""",
			("tabCRM Rep Plan", INDEX),
		)
	)


def drop_index() -> None:
	"""Put the table back into the state an upgrading site is actually in.

	The duplicates this patch exists to clean up cannot be inserted while the
	index is there, so a test that skipped this would be testing the patch
	against a table that can no longer hold the problem.
	"""
	if index_exists():
		# sql_ddl, not sql: MariaDB autocommits schema changes, and frappe refuses a
		# bare DDL statement inside a transaction that has already written
		frappe.db.sql_ddl(f"alter table `tabCRM Rep Plan` drop index `{INDEX}`")


def restore_index() -> None:
	if not index_exists():
		frappe.db.add_unique("CRM Rep Plan", ["user", "week_start"], constraint_name=INDEX)


class MergeDuplicateRepPlanWeeksTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		for email, name in ((REP, "Merge Rep"), (OTHER, "Merge Other")):
			if not frappe.db.exists("User", email):
				user = frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
				).insert(ignore_permissions=True)
				user.add_roles("Sales User")
		frappe.db.delete("CRM Rep Plan", {"user": ("in", [REP, OTHER])})

		# cleanups run after tearDown, so the rows are gone before the index returns
		self.addCleanup(restore_index)
		drop_index()

		today = frappe.utils.getdate()
		self.monday = frappe.utils.add_days(today, -today.weekday())
		self.tuesday = frappe.utils.add_days(self.monday, 1)

	def tearDown(self):
		frappe.db.delete("CRM Rep Plan", {"user": ("in", [REP, OTHER])})
		super().tearDown()

	def make_plan(self, items: list[dict], user: str = REP, week_start=None) -> str:
		"""Insert a plan, bypassing the guard that normally forbids a second one."""
		plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": user,
				"week_start": week_start or self.monday,
				"items": items,
			}
		)
		plan.flags.ignore_validate = True
		plan.insert(ignore_permissions=True)
		return plan.name

	def items_of(self, plan: str) -> list[dict]:
		return frappe.get_all(
			"CRM Rep Plan Item",
			filters={"parent": plan, "parenttype": "CRM Rep Plan"},
			fields=["activity_type", "planned_date", "note", "status", "fulfilled_by"],
		)

	def surviving_plans(self, user: str = REP) -> list[str]:
		return frappe.get_all("CRM Rep Plan", filters={"user": user}, pluck="name")

	def test_every_planned_item_survives_the_merge(self):
		"""The old cleanup deleted the smaller plan outright — these two calls would
		have become one."""
		self.make_plan([{"activity_type": "Call", "planned_date": self.monday, "note": "call Acme"}])
		self.make_plan([{"activity_type": "Call", "planned_date": self.tuesday, "note": "call Beta"}])

		merge_duplicates()

		plans = self.surviving_plans()
		self.assertEqual(len(plans), 1)
		notes = {item.note for item in self.items_of(plans[0])}
		self.assertEqual(notes, {"call Acme", "call Beta"})

	def test_the_oldest_plan_is_the_one_kept(self):
		first = self.make_plan([{"activity_type": "Task", "planned_date": self.monday, "note": "a"}])
		self.make_plan([{"activity_type": "Task", "planned_date": self.monday, "note": "b"}])

		merge_duplicates()

		self.assertEqual(self.surviving_plans(), [first])

	def test_the_same_activity_twice_collapses_to_one(self):
		self.make_plan([{"activity_type": "Call", "planned_date": self.monday, "note": "call Acme"}])
		self.make_plan([{"activity_type": "Call", "planned_date": self.monday, "note": "call Acme"}])

		merge_duplicates()

		items = self.items_of(self.surviving_plans()[0])
		self.assertEqual(len(items), 1)

	def test_a_matched_duplicate_keeps_its_fulfilment(self):
		"""If the same activity exists twice and one copy is the one the matcher
		resolved, the surviving row must be the resolved one — otherwise the merge
		quietly un-does a completed activity."""
		# a real record: fulfilled_by is a Dynamic Link and is validated on save
		task = frappe.get_doc(
			{"doctype": "CRM Task", "title": "the call that happened", "status": "Done"}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Task", task.name, force=True)

		self.make_plan([{"activity_type": "Call", "planned_date": self.monday, "note": "call Acme"}])
		self.make_plan(
			[
				{
					"activity_type": "Call",
					"planned_date": self.monday,
					"note": "call Acme",
					"status": "Done",
					"fulfilled_by_doctype": "CRM Task",
					"fulfilled_by": task.name,
				}
			]
		)

		merge_duplicates()

		items = self.items_of(self.surviving_plans()[0])
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0].status, "Done")
		self.assertEqual(str(items[0].fulfilled_by), str(task.name))

	def test_another_reps_identical_week_is_untouched(self):
		self.make_plan([{"activity_type": "Task", "planned_date": self.monday, "note": "mine"}])
		self.make_plan([{"activity_type": "Task", "planned_date": self.monday, "note": "mine too"}])
		theirs = self.make_plan(
			[{"activity_type": "Task", "planned_date": self.monday, "note": "theirs"}], user=OTHER
		)

		merge_duplicates()

		self.assertEqual(self.surviving_plans(OTHER), [theirs])

	def test_running_it_twice_changes_nothing(self):
		self.make_plan([{"activity_type": "Call", "planned_date": self.monday, "note": "one"}])
		self.make_plan([{"activity_type": "Call", "planned_date": self.tuesday, "note": "two"}])

		merge_duplicates()
		after_first = sorted(item.note for item in self.items_of(self.surviving_plans()[0]))

		merge_duplicates()
		plans = self.surviving_plans()

		self.assertEqual(len(plans), 1)
		self.assertEqual(sorted(item.note for item in self.items_of(plans[0])), after_first)

	def test_a_site_with_no_duplicates_is_left_alone(self):
		only = self.make_plan([{"activity_type": "Task", "planned_date": self.monday, "note": "solo"}])

		merge_duplicates()

		self.assertEqual(self.surviving_plans(), [only])
		self.assertEqual(len(self.items_of(only)), 1)

	def test_the_patch_leaves_the_site_with_the_index(self):
		"""The whole point of merging is to make the constraint addable, and the
		doctype hook that normally adds it only fires when the schema changes — so
		an upgrade that does not touch this doctype would otherwise clean up and
		still leave the race open."""
		self.make_plan([{"activity_type": "Task", "planned_date": self.monday, "note": "a"}])
		self.make_plan([{"activity_type": "Task", "planned_date": self.monday, "note": "b"}])
		self.assertFalse(index_exists())

		merge_duplicates()

		self.assertTrue(index_exists())


class IndexHookIsNotDestructiveTest(IntegrationTestCase):
	"""``on_doctype_update`` runs on every migrate, so it must never delete."""

	def test_the_schema_hook_deletes_nothing_when_duplicates_exist(self):
		from crm.fcrm.doctype.crm_rep_plan import crm_rep_plan

		today = frappe.utils.getdate()
		monday = frappe.utils.add_days(today, -today.weekday())
		frappe.db.delete("CRM Rep Plan", {"user": REP})
		if not frappe.db.exists("User", REP):
			frappe.get_doc(
				{"doctype": "User", "email": REP, "first_name": "Merge Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True)

		self.addCleanup(restore_index)
		drop_index()

		names = []
		for note in ("first", "second"):
			plan = frappe.get_doc(
				{
					"doctype": "CRM Rep Plan",
					"user": REP,
					"week_start": monday,
					"items": [{"activity_type": "Task", "planned_date": monday, "note": note}],
				}
			)
			plan.flags.ignore_validate = True
			plan.insert(ignore_permissions=True)
			names.append(plan.name)
		self.addCleanup(frappe.db.delete, "CRM Rep Plan", {"user": REP})

		# the index cannot be added while these exist; the hook must survive that
		# without touching a row
		crm_rep_plan.on_doctype_update()

		for name in names:
			self.assertTrue(frappe.db.exists("CRM Rep Plan", name))
