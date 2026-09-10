# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What hangs off a deal is only as private as the deal.

FCRM Note, CRM Task and CRM Call Log grant Sales User full CRUD and had no
scoping of their own, so the Notes, Tasks and Call Logs pages -- and
``frappe.client.get_list`` straight from the browser -- read every note, task
description, phone number and recording URL on the site, and a rep could delete
a manager's task. These tests knock on that door as a rep with no claim on the
record, and then check that everything a rep legitimately sees is still there:
their own rows, the tasks assigned to them, the calls they took.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

ALICE = "linkedperm-alice@crmtest.test"
MALLORY = "linkedperm-mallory@crmtest.test"
MANAGER = "linkedperm-manager@crmtest.test"


def ensure_user(email: str, name: str, role: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(role)


class LinkedRecordPermissionTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(ALICE, "Alice", "Sales User")
		ensure_user(MALLORY, "Mallory", "Sales User")
		ensure_user(MANAGER, "Linked Manager", "Sales Manager")

		# A Sales Manager outside the tree is unrestricted only at the "All
		# records" boundary; say which one this test asserts rather than inherit
		# whatever the shared site is set to.
		saved_scope = frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy")
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")
		self.addCleanup(
			frappe.db.set_single_value,
			"CRM Access Settings",
			"manager_outside_hierarchy",
			saved_scope or "All records",
		)

		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Linked Perm Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org, "deal_owner": ALICE}).insert(
			ignore_permissions=True
		)
		self.addCleanup(
			lambda: frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)
		)

		self.note = self._insert(
			{
				"doctype": "FCRM Note",
				"title": "Discount approved at 22%",
				"content": "Board approved 22% for this one only",
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal.name,
			}
		)
		self.task = self._insert(
			{
				"doctype": "CRM Task",
				"title": "Call the CFO back",
				"status": "Backlog",
				"assigned_to": ALICE,
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal.name,
			}
		)
		self.call = self._insert(
			{
				"doctype": "CRM Call Log",
				"from": "+15551110000",
				"to": "+15552220000",
				"status": "Completed",
				"type": "Incoming",
				"telephony_medium": "Twilio",
				"receiver": ALICE,
				"recording_url": "https://example.test/recording.mp3",
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal.name,
			}
		)

	def _insert(self, payload: dict):
		doc = frappe.get_doc(payload).insert(ignore_permissions=True)
		self.addCleanup(
			lambda dt=doc.doctype, dn=doc.name: (
				frappe.db.exists(dt, dn) and frappe.delete_doc(dt, dn, force=True, ignore_permissions=True)
			)
		)
		return doc

	def _names(self, doctype: str) -> list[str]:
		return [str(name) for name in frappe.get_list(doctype, pluck="name")]

	# --- the leak -------------------------------------------------------

	def test_a_rep_cannot_list_notes_on_a_deal_they_cannot_see(self):
		frappe.set_user(MALLORY)
		self.assertNotIn(str(self.note.name), self._names("FCRM Note"))

	def test_a_rep_cannot_open_a_note_on_a_deal_they_cannot_see(self):
		frappe.set_user(MALLORY)
		self.assertFalse(frappe.has_permission("FCRM Note", "read", doc=self.note.name))

	def test_a_rep_cannot_list_or_delete_a_task_on_a_deal_they_cannot_see(self):
		frappe.set_user(MALLORY)
		self.assertNotIn(str(self.task.name), self._names("CRM Task"))
		self.assertFalse(frappe.has_permission("CRM Task", "read", doc=self.task.name))
		self.assertFalse(frappe.has_permission("CRM Task", "write", doc=self.task.name))
		self.assertFalse(frappe.has_permission("CRM Task", "delete", doc=self.task.name))

	def test_a_rep_cannot_read_the_phone_numbers_on_someone_elses_deal(self):
		frappe.set_user(MALLORY)
		self.assertNotIn(str(self.call.name), self._names("CRM Call Log"))
		self.assertFalse(frappe.has_permission("CRM Call Log", "read", doc=self.call.name))

	def test_a_rep_cannot_repoint_a_hidden_note_at_their_own_deal(self):
		"""frappe checks write on the mutated document, so the check has to read the
		stored reference, not the one on the document in hand."""
		frappe.set_user(MALLORY)
		note = frappe.get_doc("FCRM Note", self.note.name)
		note.reference_doctype = None
		note.reference_docname = None
		self.assertFalse(note.has_permission("write"))

	# --- what a rep must keep seeing ------------------------------------

	def test_the_deals_owner_still_sees_everything_on_it(self):
		frappe.set_user(ALICE)
		self.assertIn(str(self.note.name), self._names("FCRM Note"))
		self.assertIn(str(self.task.name), self._names("CRM Task"))
		self.assertIn(str(self.call.name), self._names("CRM Call Log"))
		self.assertTrue(frappe.has_permission("FCRM Note", "write", doc=self.note.name))

	def test_an_assignee_sees_a_task_on_a_deal_that_is_not_theirs(self):
		task = self._insert(
			{
				"doctype": "CRM Task",
				"title": "Mallory's job on Alice's deal",
				"status": "Backlog",
				"assigned_to": MALLORY,
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal.name,
			}
		)
		frappe.set_user(MALLORY)
		self.assertIn(str(task.name), self._names("CRM Task"))
		self.assertTrue(frappe.has_permission("CRM Task", "write", doc=task.name))

	def test_a_rep_still_sees_their_own_unlinked_note(self):
		frappe.set_user(MALLORY)
		note = frappe.get_doc({"doctype": "FCRM Note", "title": "My scratchpad"}).insert()
		self.addCleanup(
			lambda: frappe.delete_doc("FCRM Note", note.name, force=True, ignore_permissions=True)
		)
		self.assertIn(str(note.name), self._names("FCRM Note"))

	def test_the_agent_who_took_the_call_still_sees_it(self):
		call = self._insert(
			{
				"doctype": "CRM Call Log",
				"from": "+15553330000",
				"to": "+15554440000",
				"status": "Completed",
				"type": "Incoming",
				"telephony_medium": "Twilio",
				"receiver": MALLORY,
			}
		)
		frappe.set_user(MALLORY)
		self.assertIn(str(call.name), self._names("CRM Call Log"))

	def test_a_call_linked_through_the_links_table_follows_the_deal(self):
		"""Twilio and Exotel attach a call to a lead or deal through ``links``, not
		``reference_docname`` -- the owner of the deal has to see those too."""
		call = self._insert(
			{
				"doctype": "CRM Call Log",
				"from": "+15555550000",
				"to": "+15556660000",
				"status": "Completed",
				"type": "Incoming",
				"telephony_medium": "Twilio",
				"links": [{"link_doctype": "CRM Deal", "link_name": self.deal.name}],
			}
		)
		frappe.set_user(ALICE)
		self.assertIn(str(call.name), self._names("CRM Call Log"))
		frappe.set_user(MALLORY)
		self.assertNotIn(str(call.name), self._names("CRM Call Log"))

	# --- who stays unrestricted ------------------------------------------

	def test_a_manager_outside_the_hierarchy_sees_the_teams_rows(self):
		frappe.set_user(MANAGER)
		self.assertIn(str(self.note.name), self._names("FCRM Note"))
		self.assertIn(str(self.task.name), self._names("CRM Task"))
		self.assertIn(str(self.call.name), self._names("CRM Call Log"))

	def test_the_administrator_is_unrestricted(self):
		frappe.set_user("Administrator")
		self.assertIn(str(self.note.name), self._names("FCRM Note"))
		self.assertIn(str(self.task.name), self._names("CRM Task"))
		self.assertIn(str(self.call.name), self._names("CRM Call Log"))

	def test_a_rep_may_still_create_a_note(self):
		frappe.set_user(MALLORY)
		self.assertTrue(frappe.has_permission("FCRM Note", "create"))
		self.assertTrue(frappe.has_permission("CRM Task", "create"))
