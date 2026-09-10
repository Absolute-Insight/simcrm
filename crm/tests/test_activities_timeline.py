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
