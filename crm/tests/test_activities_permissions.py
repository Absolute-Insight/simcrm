# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A deal's timeline must not depend on the reader being allowed to see its lead.

Lead ownership never follows the deal: ``create_deal`` copies ``lead_owner`` into
``deal_owner`` once, at conversion, and a later reassignment touches only the deal.
So every deal reassigned after conversion, and every deal converted from a lead
nobody owns (web form, import), points at a lead its owner cannot read. The
timeline used to call ``get_lead_activities`` unconditionally for such a deal and
let its ``PermissionError`` escape -- the rep saw no emails, comments, tasks or
notes on a deal that was theirs.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.activities import get_activities

OWNER = "activities-owner@crmtest.test"
OTHER = "activities-other@crmtest.test"


def ensure_rep(email: str, name: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


class DealTimelineWithUnreadableLeadTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_rep(OWNER, "Owner")
		ensure_rep(OTHER, "Other")
		self.lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Unreadable",
				"last_name": "Lead",
				"lead_owner": OTHER,
				"converted": 1,
			}
		).insert(ignore_permissions=True)
		self.deal = frappe.get_doc(
			{"doctype": "CRM Deal", "lead": self.lead.name, "deal_owner": OWNER}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)
		frappe.delete_doc("CRM Lead", self.lead.name, force=True, ignore_permissions=True)
		super().tearDown()

	def test_the_owner_of_a_deal_still_gets_its_timeline_when_the_lead_is_not_theirs(self):
		frappe.set_user(OWNER)
		# The premise: the rep may read the deal but not the lead it came from.
		self.assertTrue(frappe.has_permission("CRM Deal", "read", self.deal.name))
		self.assertFalse(frappe.has_permission("CRM Lead", "read", self.lead.name))

		activities, _calls, _notes, _tasks, _attachments = get_activities(self.deal.name)

		creation = [a for a in activities if a.get("activity_type") == "creation"]
		self.assertEqual(len(creation), 1, activities)
		self.assertIn("converted", creation[0]["data"])
		# and it is the deal's own row: nothing from the lead came through
		self.assertFalse(any(a.get("is_lead") for a in activities), activities)

	def test_a_reader_who_may_see_the_lead_gets_both_histories(self):
		frappe.set_user(OTHER)
		# OTHER owns the lead but not the deal, so they cannot open the deal at all.
		with self.assertRaises(frappe.PermissionError):
			get_activities(self.deal.name)

		frappe.set_user("Administrator")
		activities, *_rest = get_activities(self.deal.name)

		# The assertion that matters is the *merge*, not the deal's own creation
		# row -- that one is appended unconditionally, so asserting on it alone
		# passed just as well with the lead history dropped entirely.
		# get_lead_activities seeds a row of its own marked is_lead, so a reader
		# entitled to the lead sees two creation rows and an unentitled one sees
		# a single row (asserted above).
		creation = [a for a in activities if a.get("activity_type") == "creation"]
		self.assertEqual(len(creation), 2, activities)
		self.assertTrue(any(a.get("is_lead") for a in creation), activities)
		self.assertTrue(any(not a.get("is_lead") for a in creation), activities)
