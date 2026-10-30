# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The lead and deal timeline: all of the history, read cheaply.

``get_activities`` was built on frappe's ``get_docinfo``, which is a desk form's
first screen -- the latest 10 versions and 21 emails -- so a long-lived record's
Activity and Emails tabs were silently cut short. It also shipped that docinfo a
second time in the response, and looked the translatable doctypes up again for
every change.
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
