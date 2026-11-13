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


#: The least each doctype needs to be inserted.
PAYLOADS = {
	"FCRM Note": {"title": "Filed", "content": "Filed from outside"},
	"CRM Task": {"title": "Filed", "status": "Backlog"},
	"CRM Call Log": {
		"id": "filed-call",
		"from": "+15557770000",
		"to": "+15558880000",
		"status": "Completed",
		"type": "Outgoing",
		"telephony_medium": "Manual",
	},
}

#: An ordinary edit of each, which leaves the reference alone.
EDITS = {
	"FCRM Note": ("title", "Edited"),
	"CRM Task": ("title", "Edited"),
	"CRM Call Log": ("duration", 42),
}


class FilingOnARecordTest(IntegrationTestCase):
	"""A note, a task or a call log goes onto a record the user can read.

	The hook answered True for every create before it looked at the reference, and
	frappe's link validation only asks whether the record exists, so a rep filed
	onto a colleague's deal by typing its name: the row landed on that deal's
	timeline and a task assigned to its owner notified them.

	  filing-manager  (in the tree, over filing-alice)
	  filing-mallory  (a rep on nobody's team)
	  filing-outside  (a Sales Manager outside the tree, at "All records")
	"""

	ALICE = "filing-alice@crmtest.test"
	MALLORY = "filing-mallory@crmtest.test"
	TEAM_MANAGER = "filing-manager@crmtest.test"
	OUTSIDE_MANAGER = "filing-outside@crmtest.test"

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		ensure_user(self.ALICE, "Alice", "Sales User")
		ensure_user(self.MALLORY, "Mallory", "Sales User")
		ensure_user(self.TEAM_MANAGER, "Team Manager", "Sales Manager")
		ensure_user(self.OUTSIDE_MANAGER, "Outside Manager", "Sales Manager")

		for doctype, field, value in (
			("CRM Access Settings", "manager_outside_hierarchy", "All records"),
			("FCRM Settings", "enable_sales_hierarchy", 1),
		):
			saved = frappe.db.get_single_value(doctype, field)
			frappe.db.set_single_value(doctype, field, value)
			self.addCleanup(frappe.db.set_single_value, doctype, field, saved or value)
		people = [self.ALICE, self.MALLORY, self.TEAM_MANAGER, self.OUTSIDE_MANAGER]
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", people)})
		self.addCleanup(frappe.db.delete, "CRM Sales Hierarchy", {"user": ("in", people)})
		top = frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": self.TEAM_MANAGER}).insert(
			ignore_permissions=True
		)
		frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": self.ALICE, "reports_to": top.name}).insert(
			ignore_permissions=True
		)

		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Filing Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = self._keep(
			frappe.get_doc({"doctype": "CRM Deal", "organization": org, "deal_owner": self.ALICE}).insert(
				ignore_permissions=True
			)
		)
		self.lead = self._keep(
			frappe.get_doc(
				{"doctype": "CRM Lead", "first_name": "Filing", "lead_owner": self.ALICE, "status": "New"}
			).insert(ignore_permissions=True)
		)
		self.own_deal = self._keep(
			frappe.get_doc({"doctype": "CRM Deal", "organization": org, "deal_owner": self.MALLORY}).insert(
				ignore_permissions=True
			)
		)

	def _keep(self, doc):
		"""Delete ``doc`` when the test ends, whoever inserted it."""
		self.addCleanup(
			lambda dt=doc.doctype, dn=doc.name: (
				frappe.db.exists(dt, dn) and frappe.delete_doc(dt, dn, force=True, ignore_permissions=True)
			)
		)
		return doc

	def new(self, doctype: str, reference=None, **fields):
		payload = {"doctype": doctype, **PAYLOADS[doctype], **fields}
		if doctype == "CRM Call Log":
			payload["id"] = f"filed-call-{frappe.generate_hash(length=8)}"
		if reference:
			payload |= {"reference_doctype": reference.doctype, "reference_docname": reference.name}
		return frappe.get_doc(payload)

	def filed_on(self, doctype: str, reference) -> int:
		return frappe.db.count(
			doctype, {"reference_doctype": reference.doctype, "reference_docname": reference.name}
		)

	# --- the hole ---------------------------------------------------------

	def test_a_rep_cannot_file_onto_a_deal_or_lead_they_cannot_read(self):
		frappe.set_user(self.MALLORY)
		for doctype in PAYLOADS:
			for reference in (self.deal, self.lead):
				with self.subTest(doctype=doctype, reference=reference.doctype):
					with self.assertRaises(frappe.PermissionError):
						self.new(doctype, reference).insert()
					self.assertEqual(self.filed_on(doctype, reference), 0)

	def test_a_task_for_the_owner_of_a_hidden_deal_is_refused_before_it_notifies_them(self):
		frappe.set_user(self.MALLORY)
		with self.assertRaises(frappe.PermissionError):
			self.new("CRM Task", self.deal, assigned_to=self.ALICE).insert()
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("CRM Task", {"reference_docname": self.deal.name}))

	def test_a_call_log_cannot_be_linked_to_a_hidden_deal_through_its_links(self):
		"""The other link shape the scoping reads; a call linked this way shows on the deal."""
		frappe.set_user(self.MALLORY)
		with self.assertRaises(frappe.PermissionError):
			self.new(
				"CRM Call Log", links=[{"link_doctype": "CRM Deal", "link_name": self.deal.name}]
			).insert()

	def test_a_rep_cannot_move_their_own_row_onto_a_hidden_deal(self):
		"""set_value updates the document and then saves it, so the write check is
		the only one that sees the new reference."""
		frappe.set_user(self.MALLORY)
		for doctype in PAYLOADS:
			with self.subTest(doctype=doctype):
				row = self._keep(self.new(doctype, self.own_deal).insert())
				with self.assertRaises(frappe.PermissionError):
					frappe.client.set_value(doctype, row.name, "reference_docname", self.deal.name)
				with self.assertRaises(frappe.PermissionError):
					frappe.client.set_value(
						doctype,
						row.name,
						{"reference_doctype": "CRM Lead", "reference_docname": self.lead.name},
					)
				doc = frappe.get_doc(doctype, row.name)
				doc.reference_docname = self.deal.name
				with self.assertRaises(frappe.PermissionError):
					doc.save()
				self.assertEqual(
					frappe.db.get_value(doctype, row.name, "reference_docname"), self.own_deal.name
				)

	def test_a_rep_cannot_move_an_unlinked_row_onto_a_hidden_deal(self):
		frappe.set_user(self.MALLORY)
		note = self._keep(self.new("FCRM Note").insert())
		with self.assertRaises(frappe.PermissionError):
			frappe.client.set_value(
				"FCRM Note", note.name, {"reference_doctype": "CRM Deal", "reference_docname": self.deal.name}
			)

	def test_a_rep_cannot_add_a_hidden_deal_to_their_call_logs_links(self):
		frappe.set_user(self.MALLORY)
		call = self._keep(self.new("CRM Call Log", self.own_deal).insert())
		doc = frappe.get_doc("CRM Call Log", call.name)
		doc.append("links", {"link_doctype": "CRM Deal", "link_name": self.deal.name})
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	# --- what still works ---------------------------------------------------

	def assert_files_on(self, user: str, *references):
		frappe.set_user(user)
		for doctype in PAYLOADS:
			for reference in references:
				with self.subTest(user=user, doctype=doctype, reference=reference.doctype):
					row = self._keep(self.new(doctype, reference).insert())
					self.assertEqual(row.reference_docname, reference.name)
					# and edits it afterwards, the reference untouched
					frappe.client.set_value(doctype, row.name, *EDITS[doctype])
		frappe.set_user("Administrator")

	def test_the_owner_files_on_their_own_records(self):
		self.assert_files_on(self.ALICE, self.deal, self.lead)

	def test_a_rep_files_with_no_reference_at_all(self):
		frappe.set_user(self.MALLORY)
		for doctype in PAYLOADS:
			with self.subTest(doctype=doctype):
				self._keep(self.new(doctype).insert())

	def test_the_team_manager_files_on_the_teams_records(self):
		self.assert_files_on(self.TEAM_MANAGER, self.deal, self.lead)

	def test_the_team_manager_cannot_file_outside_the_team(self):
		frappe.set_user(self.TEAM_MANAGER)
		with self.assertRaises(frappe.PermissionError):
			self.new("FCRM Note", self.own_deal).insert()

	def test_a_manager_outside_the_tree_files_anywhere(self):
		self.assert_files_on(self.OUTSIDE_MANAGER, self.deal, self.own_deal)

	def test_a_system_manager_files_anywhere(self):
		self.assert_files_on("Administrator", self.deal, self.lead)

	def test_a_rep_assigned_by_todo_files_on_the_record(self):
		for reference in (self.deal, self.lead):
			frappe.get_doc(
				{
					"doctype": "ToDo",
					"reference_type": reference.doctype,
					"reference_name": reference.name,
					"allocated_to": self.MALLORY,
					"description": "Help Alice",
				}
			).insert(ignore_permissions=True)
		self.assert_files_on(self.MALLORY, self.deal, self.lead)

	def test_a_rep_moves_their_row_between_records_they_can_read(self):
		other = self._keep(
			frappe.get_doc(
				{"doctype": "CRM Lead", "first_name": "Own", "lead_owner": self.MALLORY, "status": "New"}
			).insert(ignore_permissions=True)
		)
		frappe.set_user(self.MALLORY)
		note = self._keep(self.new("FCRM Note", self.own_deal).insert())
		frappe.client.set_value(
			"FCRM Note", note.name, {"reference_doctype": "CRM Lead", "reference_docname": other.name}
		)
		self.assertEqual(frappe.db.get_value("FCRM Note", note.name, "reference_docname"), other.name)

	def test_an_assignee_still_edits_a_task_on_a_deal_they_cannot_read(self):
		"""Assigned by the deal's owner: the task is theirs, the deal is not, and
		saving it leaves the reference where it was."""
		frappe.set_user("Administrator")
		task = self._keep(
			self.new("CRM Task", self.deal, assigned_to=self.MALLORY).insert(ignore_permissions=True)
		)
		frappe.set_user(self.MALLORY)
		frappe.client.set_value("CRM Task", task.name, "status", "In Progress")
		self.assertEqual(frappe.db.get_value("CRM Task", task.name, "status"), "In Progress")

	def test_server_code_still_files_a_call_for_an_agent_who_cannot_read_the_lead(self):
		"""Twilio and Exotel save with ignore_permissions: the caller's number matched
		somebody else's lead, and the call is still the agent's who took it."""
		frappe.set_user(self.MALLORY)
		call = self._keep(self.new("CRM Call Log", self.lead, receiver=self.MALLORY, type="Incoming"))
		call.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("CRM Call Log", call.name))
