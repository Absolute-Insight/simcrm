# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A rep can edit and delete the comments they wrote, and nobody else's.

frappe grants Comment write and delete to System Manager and Website Manager
only, so ``frappe.client.set_value`` and ``frappe.client.delete`` answered 403
for every Sales User and Sales Manager on their own comment.
"""

import frappe
from frappe.desk.form.utils import update_comment
from frappe.tests import IntegrationTestCase

from crm.api.comment import add_comment, delete_comment
from crm.tests.test_row_permissions import ensure_rep

ALICE = "comment-alice@crmtest.test"
BOB = "comment-bob@crmtest.test"
MANAGER = "comment-manager@crmtest.test"


def mention(user):
	return f'<span data-type="mention" data-id="{user}" data-label="{user}">@{user}</span>'


class CommentOwnershipTest(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		ensure_rep(ALICE, "Alice")
		ensure_rep(BOB, "Bob")
		ensure_rep(MANAGER, "Manager")
		frappe.get_doc("User", MANAGER).add_roles("Sales Manager")
		self.lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Commented", "lead_owner": ALICE}
		).insert(ignore_permissions=True)
		frappe.share.add_docshare(
			"CRM Lead", self.lead.name, BOB, read=1, flags={"ignore_share_permission": 1}
		)
		frappe.share.add_docshare(
			"CRM Lead", self.lead.name, MANAGER, read=1, flags={"ignore_share_permission": 1}
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def comment_as(self, user, content="<p>First</p>"):
		frappe.set_user(user)
		return add_comment("CRM Lead", self.lead.name, content).name

	def test_a_rep_edits_their_own_comment(self):
		name = self.comment_as(ALICE)

		update_comment(name, "<p>Second</p>")

		self.assertEqual(frappe.db.get_value("Comment", name, "content"), "<p>Second</p>")

	def test_a_rep_cannot_edit_a_colleagues_comment(self):
		name = self.comment_as(ALICE)

		frappe.set_user(BOB)
		with self.assertRaises(frappe.PermissionError):
			update_comment(name, "<p>Second</p>")

	def test_a_rep_deletes_their_own_comment(self):
		name = self.comment_as(ALICE)

		delete_comment(name)

		self.assertFalse(frappe.db.exists("Comment", name))

	def test_a_manager_deletes_their_own_comment(self):
		name = self.comment_as(MANAGER)

		delete_comment(name)

		self.assertFalse(frappe.db.exists("Comment", name))

	def test_a_rep_cannot_delete_a_colleagues_comment(self):
		name = self.comment_as(ALICE)

		frappe.set_user(BOB)
		with self.assertRaises(frappe.PermissionError):
			delete_comment(name)

		self.assertTrue(frappe.db.exists("Comment", name))

	def test_a_manager_cannot_delete_a_reps_comment(self):
		name = self.comment_as(ALICE)

		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			delete_comment(name)

		self.assertTrue(frappe.db.exists("Comment", name))

	def test_a_rep_who_lost_the_record_cannot_delete_their_comment(self):
		name = self.comment_as(BOB)
		frappe.set_user("Administrator")
		frappe.share.remove("CRM Lead", self.lead.name, BOB)

		frappe.set_user(BOB)
		with self.assertRaises(frappe.PermissionError):
			delete_comment(name)

		self.assertTrue(frappe.db.exists("Comment", name))

	def test_only_a_written_comment_can_be_deleted(self):
		frappe.set_user(ALICE)
		info = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "CRM Lead",
				"reference_name": self.lead.name,
				"content": "Status changed",
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.PermissionError):
			delete_comment(info.name)

		self.assertTrue(frappe.db.exists("Comment", info.name))

	def test_a_guest_comment_is_not_deletable_by_guest(self):
		frappe.set_user("Guest")
		guest = frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Lead",
				"reference_name": self.lead.name,
				"content": "Left by a visitor",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(guest.owner, "Guest")

		with self.assertRaises(frappe.PermissionError):
			delete_comment(guest.name)

	def test_deleting_a_comment_takes_its_mention_notifications_with_it(self):
		name = self.comment_as(ALICE, f"<p>Look {mention(BOB)}</p>")
		notification = {"notification_type_doctype": "Comment", "notification_type_doc": name}
		self.assertTrue(frappe.db.exists("CRM Notification", {**notification, "to_user": BOB}))

		delete_comment(name)

		self.assertFalse(frappe.db.exists("Comment", name))
		self.assertFalse(frappe.db.exists("CRM Notification", notification))

	def test_editing_a_comment_does_not_notify_the_same_people_again(self):
		name = self.comment_as(ALICE, f"<p>Look {mention(BOB)}</p>")

		update_comment(name, f"<p>Look again {mention(BOB)}</p>")

		self.assertEqual(
			frappe.db.count(
				"CRM Notification",
				{"notification_type_doctype": "Comment", "notification_type_doc": name, "to_user": BOB},
			),
			1,
		)

	def test_editing_a_new_mention_into_a_comment_notifies_them(self):
		name = self.comment_as(ALICE, "<p>Look</p>")

		update_comment(name, f"<p>Look {mention(BOB)}</p>")

		self.assertTrue(
			frappe.db.exists(
				"CRM Notification",
				{"notification_type_doctype": "Comment", "notification_type_doc": name, "to_user": BOB},
			)
		)

	def test_deleting_a_comment_updates_the_cached_list_on_the_record(self):
		name = self.comment_as(ALICE, "<p>Unique marker text</p>")
		self.assertIn("Unique marker text", frappe.db.get_value("CRM Lead", self.lead.name, "_comments"))

		delete_comment(name)

		self.assertNotIn(
			"Unique marker text", frappe.db.get_value("CRM Lead", self.lead.name, "_comments") or ""
		)
