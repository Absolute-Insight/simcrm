# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Row-level access on CRM Telephony Agent.

One row per user, named by that user, routing that user's calls. The settings
pane writes it through ``frappe.client`` with the session user's role grants
and Sales User holds write and delete on the doctype, so the permission hooks
are what stop a rep from re-routing or deleting a colleague's agent.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

ALICE = "telagent-alice@crmtest.test"
BOB = "telagent-bob@crmtest.test"
MANAGER = "telagent-manager@crmtest.test"

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


def ensure_user(email: str, name: str, role: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(role)


class IntegrationTestCRMTelephonyAgent(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(ALICE, "Alice", "Sales User")
		ensure_user(BOB, "Bob", "Sales User")
		ensure_user(MANAGER, "Telephony Manager", "Sales Manager")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(self.clear_agents)
		self.clear_agents()
		self.bobs_agent = frappe.get_doc(
			{"doctype": "CRM Telephony Agent", "user": BOB, "twilio_number": "+15550000002"}
		).insert(ignore_permissions=True)

	@staticmethod
	def clear_agents():
		frappe.set_user("Administrator")
		for user in (ALICE, BOB, MANAGER):
			if frappe.db.exists("CRM Telephony Agent", user):
				frappe.delete_doc("CRM Telephony Agent", user, force=True, ignore_permissions=True)

	def test_a_rep_cannot_list_or_read_another_reps_agent(self):
		frappe.set_user(ALICE)
		listed = [row["name"] for row in frappe.client.get_list("CRM Telephony Agent", fields=["name"])]
		self.assertNotIn(BOB, listed)
		self.assertFalse(frappe.has_permission("CRM Telephony Agent", doc=BOB, ptype="read"))

	def test_a_rep_cannot_reroute_or_delete_another_reps_agent(self):
		frappe.set_user(ALICE)
		self.assertFalse(frappe.has_permission("CRM Telephony Agent", doc=BOB, ptype="write"))
		self.assertFalse(frappe.has_permission("CRM Telephony Agent", doc=BOB, ptype="delete"))
		with self.assertRaises(frappe.PermissionError):
			frappe.client.set_value("CRM Telephony Agent", BOB, "twilio_number", "+15550000001")
		with self.assertRaises(frappe.PermissionError):
			frappe.client.delete("CRM Telephony Agent", BOB)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CRM Telephony Agent", BOB, "twilio_number"), "+15550000002")

	def test_a_rep_cannot_plant_an_agent_under_another_users_name(self):
		frappe.set_user(ALICE)
		with self.assertRaises(frappe.PermissionError):
			frappe.client.insert({"doctype": "CRM Telephony Agent", "user": MANAGER, "twilio_number": "+1"})
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("CRM Telephony Agent", MANAGER))

	def test_a_rep_still_owns_their_own_agent(self):
		frappe.set_user(ALICE)
		own = frappe.client.insert(
			{"doctype": "CRM Telephony Agent", "user": ALICE, "twilio_number": "+15550000001"}
		)
		self.assertEqual(own["name"], ALICE)
		frappe.client.set_value("CRM Telephony Agent", ALICE, "twilio_number", "+15550000003")
		self.assertEqual(
			[row["name"] for row in frappe.client.get_list("CRM Telephony Agent", fields=["name"])],
			[ALICE],
		)
		self.assertEqual(frappe.db.get_value("CRM Telephony Agent", ALICE, "twilio_number"), "+15550000003")

	def test_a_sales_manager_maintains_every_agent(self):
		frappe.set_user(MANAGER)
		self.assertTrue(frappe.has_permission("CRM Telephony Agent", doc=BOB, ptype="write"))
		frappe.client.set_value("CRM Telephony Agent", BOB, "twilio_number", "+15550000009")
		self.assertIn(
			BOB, [row["name"] for row in frappe.client.get_list("CRM Telephony Agent", fields=["name"])]
		)
