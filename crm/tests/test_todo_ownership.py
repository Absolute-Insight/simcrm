# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Ownership moves with a ToDo, so a ToDo is not something anyone may insert.

``crm.api.todo.after_insert`` mirrors an assignment into ``lead_owner`` /
``deal_owner``, and frappe's ToDo grants create to the ``All`` role: without a
check of its own, ``frappe.client.insert`` on a guessed deal name was a way to
take any deal, or to hand it to anyone. The same row is the second clause that
grants a rep visibility of a record under the sales hierarchy.

The other half is the way back out: cancelling an assignment used to clear the
owner whoever the assignee was, so removing a co-assignee dropped the record out
of its owner's pipeline, reports and quota.
"""

from __future__ import annotations

import frappe
from frappe.desk.form.assign_to import add as assign_to_add
from frappe.tests import IntegrationTestCase

from crm.api.doc import remove_assignments

ALICE = "todoown-alice@crmtest.test"
BOB = "todoown-bob@crmtest.test"
MALLORY = "todoown-mallory@crmtest.test"


def ensure_user(email: str, name: str, role: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(role)


class ToDoOwnershipTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(ALICE, "Alice", "Sales User")
		ensure_user(BOB, "Bob", "Sales User")
		ensure_user(MALLORY, "Mallory", "Sales User")
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "ToDo Own Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.org, "deal_owner": ALICE}
		).insert(ignore_permissions=True)
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.set_user("Administrator")
		frappe.db.delete("ToDo", {"reference_type": "CRM Deal", "reference_name": self.deal.name})
		frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)

	def _owner(self) -> str | None:
		return frappe.db.get_value("CRM Deal", self.deal.name, "deal_owner")

	def _insert_todo(self, allocated_to: str):
		return frappe.get_doc(
			{
				"doctype": "ToDo",
				"reference_type": "CRM Deal",
				"reference_name": self.deal.name,
				"allocated_to": allocated_to,
				"status": "Open",
				"description": "Planted",
			}
		).insert()

	# --- taking a record by inserting a ToDo ----------------------------

	def test_a_rep_cannot_take_a_deal_by_inserting_a_todo(self):
		"""The critical one: Sales User has create on ToDo, deal names are guessable."""
		frappe.set_user(MALLORY)
		with self.assertRaises(frappe.PermissionError):
			self._insert_todo(MALLORY)

		frappe.set_user("Administrator")
		self.assertEqual(self._owner(), ALICE)
		self.assertFalse(
			frappe.db.exists(
				"ToDo",
				{"reference_type": "CRM Deal", "reference_name": self.deal.name, "allocated_to": MALLORY},
			)
		)

	def test_the_refused_assignment_does_not_open_the_deal_either(self):
		"""The ToDo row is one of the two clauses org_hierarchy reads. Refusing it
		after the row is written would be too late -- and circular, because the row
		grants the very permission the check asks about."""
		frappe.set_user(MALLORY)
		self.assertFalse(frappe.has_permission("CRM Deal", "read", doc=self.deal.name))
		with self.assertRaises(frappe.PermissionError):
			self._insert_todo(MALLORY)
		self.assertFalse(frappe.has_permission("CRM Deal", "read", doc=self.deal.name))
		self.assertNotIn(self.deal.name, frappe.get_list("CRM Deal", pluck="name"))

	def test_a_rep_cannot_hand_someone_elses_deal_to_a_third_party(self):
		frappe.set_user(MALLORY)
		with self.assertRaises(frappe.PermissionError):
			self._insert_todo(BOB)
		frappe.set_user("Administrator")
		self.assertEqual(self._owner(), ALICE)

	# --- the assignment flows that must keep working --------------------

	def test_an_authorised_assignment_still_moves_the_owner(self):
		"""What the frontend's AssignmentModal calls, as someone who may write the deal."""
		frappe.set_user("Administrator")
		assign_to_add({"assign_to": [BOB], "doctype": "CRM Deal", "name": self.deal.name})
		self.assertEqual(self._owner(), BOB)

	def test_the_owner_may_hand_their_own_deal_over(self):
		frappe.set_user(ALICE)
		assign_to_add({"assign_to": [BOB], "doctype": "CRM Deal", "name": self.deal.name})
		frappe.set_user("Administrator")
		self.assertEqual(self._owner(), BOB)

	def test_a_rep_creating_their_own_deal_still_gets_the_assignment(self):
		"""CRM Deal.after_insert -> assign_agent inserts a ToDo for the owner it just
		wrote. The gate must not fire on an assignment that changes nothing."""
		frappe.set_user(ALICE)
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": self.org, "deal_owner": ALICE}).insert()
		self.addCleanup(lambda: frappe.delete_doc("CRM Deal", deal.name, force=True, ignore_permissions=True))
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "deal_owner"), ALICE)
		self.assertTrue(
			frappe.db.exists(
				"ToDo", {"reference_type": "CRM Deal", "reference_name": deal.name, "allocated_to": ALICE}
			)
		)

	# --- removing an assignment -----------------------------------------

	def test_remove_assignments_refuses_a_caller_who_cannot_write_the_record(self):
		frappe.set_user(MALLORY)
		with self.assertRaises(frappe.PermissionError):
			remove_assignments("CRM Deal", self.deal.name, [ALICE])
		frappe.set_user("Administrator")
		self.assertEqual(self._owner(), ALICE)

	def test_removing_a_co_assignee_leaves_the_owner_alone(self):
		"""A manager co-assigns Bob to Alice's deal and Bob steps off it again. The
		deal is still Alice's -- it used to fall out of her pipeline and quota."""
		frappe.set_user("Administrator")
		assign_to_add({"assign_to": [BOB], "doctype": "CRM Deal", "name": self.deal.name})
		frappe.db.set_value("CRM Deal", self.deal.name, "deal_owner", ALICE, update_modified=False)

		remove_assignments("CRM Deal", self.deal.name, [BOB])

		self.assertEqual(self._owner(), ALICE)

	def test_removing_the_owners_own_assignment_still_clears_the_owner(self):
		frappe.set_user("Administrator")
		self.assertEqual(self._owner(), ALICE)

		remove_assignments("CRM Deal", self.deal.name, [ALICE])

		self.assertIsNone(self._owner())
