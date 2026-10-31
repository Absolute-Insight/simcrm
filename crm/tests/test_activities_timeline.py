# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""One save that changes several fields is several timeline entries.

Both version loops read ``changed[0]`` and dropped the rest, so a save that
moved the status and the owner together logged the status only -- and an audit
of who took a deal over found nothing.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.activities import get_deal_activities, get_lead_activities

OWNER = "timeline-owner@crmtest.test"


def _changed_fields(activities: list[dict]) -> list[str]:
	"""Every field named on the timeline.

	``handle_multiple_versions`` folds consecutive changes by the same author
	into one entry with the rest under ``other_versions``, so both levels count.
	"""
	fields = []
	for activity in activities:
		if activity.get("activity_type") not in ("changed", "added", "removed"):
			continue
		for version in [activity, *activity.get("other_versions", [])]:
			data = version.get("data") or {}
			if isinstance(data, dict) and data.get("field"):
				fields.append(data["field"])
	return fields


class TimelineChangedFieldsTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", OWNER):
			frappe.get_doc(
				{"doctype": "User", "email": OWNER, "first_name": "Timeline", "send_welcome_email": 0}
			).insert(ignore_permissions=True).add_roles("Sales User")

	def _version(self, ref_doctype: str, docname: str, changed: list[list]):
		version = frappe.get_doc(
			{
				"doctype": "Version",
				"ref_doctype": ref_doctype,
				"docname": str(docname),
				"data": json.dumps({"changed": changed}),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("Version", version.name, force=True, ignore_permissions=True)
		)

	def test_a_deal_save_that_changes_status_and_owner_logs_both(self):
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Timeline Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("CRM Deal", deal.name, force=True, ignore_permissions=True))
		self._version(
			"CRM Deal",
			deal.name,
			[["status", "Qualification", "Demo/Making"], ["deal_owner", "Administrator", OWNER]],
		)

		activities = get_deal_activities(deal.name)[0]

		fields = _changed_fields(activities)
		self.assertIn("status", fields)
		self.assertIn("deal_owner", fields)

	def test_a_lead_save_that_changes_status_and_owner_logs_both(self):
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Timeline"}).insert(
			ignore_permissions=True
		)
		self.addCleanup(lambda: frappe.delete_doc("CRM Lead", lead.name, force=True, ignore_permissions=True))
		self._version(
			"CRM Lead",
			lead.name,
			[["status", "New", "Contacted"], ["lead_owner", "Administrator", OWNER]],
		)

		activities = get_lead_activities(lead.name)[0]

		fields = _changed_fields(activities)
		self.assertIn("status", fields)
		self.assertIn("lead_owner", fields)


class TimelineEmailDirectionTest(IntegrationTestCase):
	"""Reply needs to know which way an email went.

	frappe's docinfo leaves ``sent_or_received`` out, so Reply on mail the rep
	sent addressed the rep's own mailbox instead of the customer.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def _email(self, doctype: str, name: str, direction: str, sender: str, recipients: str):
		communication = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": direction,
				"subject": f"{direction} quote",
				"content": "<p>Quote attached</p>",
				"sender": sender,
				"recipients": recipients,
				"reference_doctype": doctype,
				"reference_name": name,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc(
				"Communication", communication.name, force=True, ignore_permissions=True
			)
		)

	def _directions(self, activities: list[dict]) -> dict[str, str]:
		return {
			a["data"]["subject"]: a["data"].get("sent_or_received")
			for a in activities
			if a.get("activity_type") == "communication"
		}

	def test_a_deal_timeline_says_which_emails_were_sent_and_which_received(self):
		deal = frappe.get_doc({"doctype": "CRM Deal"}).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("CRM Deal", deal.name, force=True, ignore_permissions=True))
		self._email("CRM Deal", deal.name, "Sent", "rep@crmtest.test", "buyer@customer.test")
		self._email("CRM Deal", deal.name, "Received", "buyer@customer.test", "rep@crmtest.test")

		directions = self._directions(get_deal_activities(deal.name)[0])

		self.assertEqual(directions, {"Sent quote": "Sent", "Received quote": "Received"})

	def test_a_lead_timeline_says_which_emails_were_sent_and_which_received(self):
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Direction"}).insert(
			ignore_permissions=True
		)
		self.addCleanup(lambda: frappe.delete_doc("CRM Lead", lead.name, force=True, ignore_permissions=True))
		self._email("CRM Lead", lead.name, "Sent", "rep@crmtest.test", "buyer@customer.test")
		self._email("CRM Lead", lead.name, "Received", "buyer@customer.test", "rep@crmtest.test")

		directions = self._directions(get_lead_activities(lead.name)[0])

		self.assertEqual(directions, {"Sent quote": "Sent", "Received quote": "Received"})
