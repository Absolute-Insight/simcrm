# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The lead and deal timeline: all of the history, read cheaply.

``get_activities`` was built on frappe's ``get_docinfo``, which is a desk form's
first screen -- the latest 10 versions and 21 emails -- so a long-lived record's
Activity and Emails tabs were silently cut short. It also shipped that docinfo a
second time in the response, looked the translatable doctypes up again for
every change, and read its four linked tables on columns no index leads with.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.translate import get_translated_doctypes

import crm.api.activities as activities_api
from crm.api.activities import get_activities


def make_lead(first_name: str) -> str:
	return (
		frappe.get_doc({"doctype": "CRM Lead", "first_name": first_name, "last_name": "Feed"})
		.insert(ignore_permissions=True)
		.name
	)


def add_versions(lead: str, count: int, field: str = "job_title") -> None:
	for index in range(count):
		frappe.get_doc(
			{
				"doctype": "Version",
				"ref_doctype": "CRM Lead",
				"docname": lead,
				"data": json.dumps({"changed": [[field, f"Value {index}", f"Value {index + 1}"]]}),
			}
		).insert(ignore_permissions=True)


def add_emails(lead: str, count: int) -> None:
	for index in range(count):
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Sent",
				"subject": f"Email {index}",
				"content": f"Body {index}",
				"sender": "feed-sender@example.com",
				"recipients": "feed-lead@example.com",
				"reference_doctype": "CRM Lead",
				"reference_name": lead,
			}
		).insert(ignore_permissions=True)


def changes(activities: list[dict]) -> int:
	"""Every field change on the timeline, including the ones folded under another."""
	return sum(
		1 + len(activity.get("other_versions", []))
		for activity in activities
		if activity.get("activity_type") in ("changed", "added", "removed")
	)


def emails(activities: list[dict]) -> int:
	return sum(1 for activity in activities if activity.get("activity_type") == "communication")


class TimelineHistoryTest(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.lead = make_lead("History")

	def tearDown(self):
		frappe.db.rollback()

	def test_the_timeline_is_not_cut_at_desks_first_screen(self):
		add_versions(self.lead, 12)
		add_emails(self.lead, 25)

		result = get_activities(self.lead)

		self.assertEqual(changes(result[0]), 12, "every save is on the Activity tab")
		self.assertEqual(emails(result[0]), 25, "every email is on the Emails tab")
		self.assertFalse(result[5], "nothing older is left to load")

	def test_a_history_longer_than_the_page_says_so(self):
		add_versions(self.lead, 6)

		result = get_activities(self.lead, page_length=5)

		self.assertEqual(changes(result[0]), 5)
		self.assertTrue(result[5], "the timeline has to say there is more")

		result = get_activities(self.lead, page_length=10)

		self.assertEqual(changes(result[0]), 6)
		self.assertFalse(result[5])


class TimelineHotPathTest(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.lead = make_lead("Hot Path")

	def tearDown(self):
		frappe.db.rollback()

	def test_the_translatable_doctypes_are_read_once_per_call(self):
		# status is a Link, so each change asks whether its doctype is translated
		add_versions(self.lead, 8, field="status")

		with patch.object(
			activities_api, "get_translated_doctypes", side_effect=get_translated_doctypes
		) as lookup:
			get_activities(self.lead)

		self.assertEqual(lookup.call_count, 1)

	def test_the_response_does_not_carry_the_docinfo_a_second_time(self):
		add_emails(self.lead, 1)
		frappe.response.pop("docinfo", None)

		get_activities(self.lead)

		self.assertNotIn("docinfo", frappe.response)


class TimelineReadsUseIndexesTest(IntegrationTestCase):
	"""Calls, notes, tasks and call links were read on the record's name alone.

	Every index on those tables leads with the doctype column, and MariaDB has no
	skip-scan, so each one was a full table scan on every page load -- twice for
	a converted deal. FCRM Note had no index at all.
	"""

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def declared_indexes(self) -> dict[str, list[tuple[str, ...]]]:
		from crm.fcrm.doctype.crm_call_log import crm_call_log
		from crm.fcrm.doctype.crm_task import crm_task
		from crm.fcrm.doctype.fcrm_note import fcrm_note

		# frappe's own, on Dynamic Link
		declared = {"Dynamic Link": [("link_doctype", "link_name")]}

		def add_index(doctype, fields, index_name=None):
			declared.setdefault(doctype, []).append(tuple(fields))

		with patch.object(frappe.db, "add_index", side_effect=add_index):
			for module in (crm_task, crm_call_log, fcrm_note):
				hook = getattr(module, "on_doctype_update", None)
				if hook:
					hook()
		return declared

	def test_fcrm_note_declares_its_record_index_and_migrate_applies_it(self):
		import crm.hooks

		self.assertIn(
			("reference_doctype", "reference_docname"), self.declared_indexes().get("FCRM Note", [])
		)
		self.assertIn("crm.fcrm.doctype.fcrm_note.fcrm_note.on_doctype_update", crm.hooks.after_migrate)

	def test_every_feed_read_leads_with_an_indexed_column(self):
		declared = self.declared_indexes()
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Feed Index Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		lead = make_lead("Indexed")
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org, "lead": lead}).insert(
			ignore_permissions=True
		)

		reads = []
		real_get_all = frappe.db.get_all

		def get_all(doctype, *args, **kwargs):
			reads.append((doctype, kwargs.get("filters")))
			return real_get_all(doctype, *args, **kwargs)

		with patch.object(frappe.db, "get_all", side_effect=get_all):
			get_activities(deal.name)

		checked = set()
		for doctype, filters in reads:
			if doctype not in ("CRM Call Log", "Dynamic Link", "FCRM Note", "CRM Task"):
				continue
			if "name" in filters:
				continue  # by primary key
			leading = {index[0] for index in declared.get(doctype, [])}
			self.assertTrue(
				leading & set(filters),
				f"{doctype} is read on {sorted(filters)}, and no index leads with any of them",
			)
			checked.add(doctype)
		self.assertEqual(checked, {"CRM Call Log", "Dynamic Link", "FCRM Note", "CRM Task"})
