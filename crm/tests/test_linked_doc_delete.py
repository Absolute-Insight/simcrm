# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deleting a record that other records point at.

The "Unlink" choice in the delete modals has to take away only the link to the
record going, and a bulk delete has to treat each record's unlinking and its
delete as one thing that either happens or does not.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.doc import _unlink_linked_docs, delete_bulk_docs, get_linked_docs_of_document
from crm.fcrm.doctype.crm_deal.crm_deal import CRMDeal


def make_contact(first_name: str) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first_name,
				"last_name": f"Unlink {frappe.generate_hash(length=6)}",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_org() -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": f"Unlink Org {frappe.generate_hash(length=6)}",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class UnlinkOneContactTest(IntegrationTestCase):
	"""frappe reports a CRM Contacts child row as its parent deal, so the unlink is
	handed the deal. It used to clear the deal's whole contacts table -- and with
	no primary contact left, the deal's email and phone -- for one contact going.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.a, self.b, self.c = (make_contact(name) for name in ("Alpha", "Bravo", "Charlie"))
		self.deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": make_org(),
				"contacts": [
					{"contact": self.b, "is_primary": 1},
					{"contact": self.a},
					{"contact": self.c},
				],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def contacts_left(self) -> list[str]:
		return sorted(frappe.get_all("CRM Contacts", filters={"parent": self.deal.name}, pluck="contact"))

	def test_the_delete_modal_unlink_keeps_the_deals_other_contacts(self):
		linked = get_linked_docs_of_document("Contact", self.a)
		items = [{"doctype": d["reference_doctype"], "docname": d["reference_docname"]} for d in linked]
		self.assertIn({"doctype": "CRM Deal", "docname": self.deal.name}, items)

		# through frappe.call, as the HTTP handler calls it: arguments the
		# function does not take are dropped rather than raising
		result = frappe.call(
			"crm.api.doc.remove_linked_doc_reference",
			items=items,
			remove_contact=True,
			contact=self.a,
		)

		self.assertIn(self.deal.name, result["unlinked"])
		self.assertEqual(self.contacts_left(), sorted([self.b, self.c]))
		deal = frappe.get_doc("CRM Deal", self.deal.name)
		self.assertEqual([row.contact for row in deal.contacts if row.is_primary], [self.b])

	def test_the_bulk_unlink_keeps_the_deals_other_contacts(self):
		_unlink_linked_docs("Contact", [self.a])

		self.assertEqual(self.contacts_left(), sorted([self.b, self.c]))

	def test_unlinking_a_contact_without_naming_it_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.call(
				"crm.api.doc.remove_linked_doc_reference",
				items=[{"doctype": "CRM Deal", "docname": self.deal.name}],
				remove_contact=True,
			)
		self.assertEqual(len(self.contacts_left()), 3)


class UnlinkContactReportsWhatItDidTest(IntegrationTestCase):
	"""The contact branch of the unlink was hard-coded to success: a document
	that holds the contact some other way was reported unlinked and left as it
	was, the modal closed, and the contact still refused to delete."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.contact = make_contact("Referenced")
		self.other = make_contact("Bystander")

	def tearDown(self):
		frappe.db.rollback()

	def make(self, doctype: str, contact: str, **fields):
		return frappe.get_doc(
			{
				"doctype": doctype,
				"title": "About the contact",
				"reference_doctype": "Contact",
				"reference_docname": contact,
				**fields,
			}
		).insert(ignore_permissions=True)

	def unlink(self, *docs):
		return frappe.call(
			"crm.api.doc.remove_linked_doc_reference",
			items=[{"doctype": doc.doctype, "docname": doc.name} for doc in docs],
			remove_contact=True,
			contact=self.contact,
		)

	def reference_of(self, doc) -> tuple:
		return frappe.db.get_value(doc.doctype, doc.name, ["reference_doctype", "reference_docname"])

	def test_a_task_and_a_note_that_reference_the_contact_are_really_unlinked(self):
		task, note = self.make("CRM Task", self.contact), self.make("FCRM Note", self.contact)

		result = self.unlink(task, note)

		self.assertEqual(result, {"unlinked": [task.name, note.name], "skipped": []})
		for doc in (task, note):
			self.assertFalse(any(self.reference_of(doc)), doc.doctype)

	def test_a_document_that_does_not_hold_the_contact_is_not_reported_unlinked(self):
		# it references another contact: nothing of this contact's to clear
		task = self.make("CRM Task", self.other)

		result = self.unlink(task)

		self.assertEqual(
			result, {"unlinked": [], "skipped": [{"docname": task.name, "reason": "not_unlinkable"}]}
		)
		self.assertEqual(self.reference_of(task), ("Contact", self.other))

	def test_a_document_that_will_not_save_is_not_reported_unlinked(self):
		task = self.make("CRM Task", self.contact)

		with patch(
			"frappe.model.document.Document.save", side_effect=frappe.ValidationError("will not save")
		):
			result = self.unlink(task)

		self.assertEqual(
			result, {"unlinked": [], "skipped": [{"docname": task.name, "reason": "not_unlinkable"}]}
		)


class BulkDeleteIsPerRecordTest(IntegrationTestCase):
	"""Unlink-then-delete ran as two passes: every record's links first, then
	frappe's delete loop, which commits after each success and rolls back after
	each failure. A record that would not delete survived without its notes, or
	a failure early in the batch rolled the others' unlinking back and failed
	them too -- and either way the response counted every record as deleted.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.made: list[tuple[str, str]] = []
		self.addCleanup(self.purge)
		org = self.made_one("CRM Organization", make_org())
		self.plain = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert(
			ignore_permissions=True
		)
		self.made_one("CRM Deal", self.plain.name)
		self.plain_note = self.note_on(self.plain.name)
		self.blocked = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert(
			ignore_permissions=True
		)
		self.made_one("CRM Deal", self.blocked.name)
		self.blocked_note = self.note_on(self.blocked.name)
		# A link the unlink step cannot take away (a Contact's Dynamic Link row, not
		# a reference_docname), so this deal cannot be deleted.
		self.made_one("Contact", self.contact_linked_to(self.blocked.name))

	def tearDown(self):
		frappe.db.rollback()

	def made_one(self, doctype: str, name: str) -> str:
		self.made.append((doctype, name))
		return name

	def purge(self):
		# The old two-pass delete went through frappe's delete_bulk, which commits
		# after every record it deletes -- and so commits this setup with it. What
		# outlived tearDown's rollback has to be removed the same way.
		left = [(doctype, name) for doctype, name in reversed(self.made) if frappe.db.exists(doctype, name)]
		for doctype, name in left:
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		if left:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def contact_linked_to(self, deal: str) -> str:
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": f"Blocker {frappe.generate_hash(length=6)}",
				"links": [{"link_doctype": "CRM Deal", "link_name": deal}],
			}
		)
		return contact.insert(ignore_permissions=True).name

	def note_on(self, deal: str) -> str:
		return self.made_one(
			"FCRM Note",
			frappe.get_doc(
				{
					"doctype": "FCRM Note",
					"title": f"Note on {deal}",
					"reference_doctype": "CRM Deal",
					"reference_docname": deal,
				}
			)
			.insert(ignore_permissions=True)
			.name,
		)

	def assert_outcome(self, result):
		self.assertFalse(frappe.db.exists("CRM Deal", self.plain.name))
		self.assertFalse(frappe.db.get_value("FCRM Note", self.plain_note, "reference_docname"))

		self.assertTrue(frappe.db.exists("CRM Deal", self.blocked.name))
		self.assertEqual(
			frappe.db.get_value("FCRM Note", self.blocked_note, "reference_docname"),
			self.blocked.name,
			"the deal that survived lost its note",
		)

		self.assertEqual(result["count"], 1, "only one deal was deleted")
		self.assertEqual([row["docname"] for row in result["failed"]], [self.blocked.name])
		self.assertIn("linked with Contact", result["failed"][0]["reason"])

	def test_a_record_that_will_not_delete_keeps_its_links(self):
		self.assert_outcome(delete_bulk_docs("CRM Deal", [self.plain.name, self.blocked.name]))

	def test_a_failure_first_does_not_take_the_rest_down_with_it(self):
		self.assert_outcome(delete_bulk_docs("CRM Deal", [self.blocked.name, self.plain.name]))

	def test_a_restored_linked_doc_keeps_what_hangs_off_it_after_the_commit(self):
		"""Deleting a note queues, for after the commit, the removal of its
		comments, assignments and versions. Rolling back to the savepoint brings
		the note back but does not take that callback off the queue, so the next
		commit used to strip a note that is still there.

		Under test frappe runs that callback inline, inside the savepoint, so the
		rollback undid it; here it is held for the commit, as it is on a site.
		"""
		comment = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "FCRM Note",
				"reference_name": self.blocked_note,
				"content": "still wanted",
			}
		).insert(ignore_permissions=True)

		enqueue = frappe.enqueue

		def after_the_commit(method, **kwargs):
			if not kwargs.pop("enqueue_after_commit", False):
				return enqueue(method, **kwargs)
			kwargs["now"] = True
			frappe.db.after_commit.add(lambda: enqueue(method, **kwargs))

		# "Delete" takes the enrichment run with the deal's other linked docs, so
		# it no longer stands in the way; the deal refuses to go on its own instead.
		blocked = self.blocked.name

		def on_trash(doc):
			if doc.name == blocked:
				frappe.throw("This deal is still needed")

		with (
			patch("frappe.enqueue", after_the_commit),
			patch.object(CRMDeal, "on_trash", on_trash, create=True),
		):
			result = delete_bulk_docs("CRM Deal", [self.plain.name, self.blocked.name], delete_linked=True)
		frappe.db.after_commit.run()

		self.assertEqual([row["docname"] for row in result["failed"]], [self.blocked.name])
		self.assertFalse(frappe.db.exists("FCRM Note", self.plain_note))
		self.assertTrue(frappe.db.exists("FCRM Note", self.blocked_note))
		self.assertTrue(
			frappe.db.exists("Comment", comment.name), "the surviving deal's note lost its comments"
		)

	def test_a_failure_first_leaves_the_rest_their_realtime_updates(self):
		"""frappe queues the realtime flush once per transaction, when it first
		makes the buffer on frappe.local. A failure that made it lost the flush
		to the rollback but kept the buffer, so nothing deleted after it ever
		told an open list it had gone. Webhooks and link counts work the same way.
		"""
		# The setup's inserts made the buffer already; start the transaction clean.
		frappe.realtime.clear_realtime_log()
		frappe.db.after_commit.reset()

		delete_bulk_docs("CRM Deal", [self.blocked.name, self.plain.name])

		sent = []
		with patch("frappe.realtime.emit_via_redis", lambda *args: sent.append(args)):
			frappe.db.after_commit.run()

		updated = {(message.get("doctype"), message.get("name")) for event, message, room in sent}
		self.assertIn(("CRM Deal", self.plain.name), updated, "the deleted deal's update never went out")
		self.assertNotIn(
			("FCRM Note", self.blocked_note), updated, "an unlink the rollback undid was still announced"
		)
