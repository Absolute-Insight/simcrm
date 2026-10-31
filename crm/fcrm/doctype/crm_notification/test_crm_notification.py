# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.crm_notification.crm_notification import has_permission, notify_user

SYSTEM_MANAGER = "crm.admin@example.com"  # System Manager from crm/tests/test_records.json
USER1 = "crm.user1@example.com"
USER2 = "crm.user2@example.com"


class TestCRMNotificationPermission(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_system_manager_can_create(self):
		self.assertTrue(has_permission(make_notification(USER1), "create", SYSTEM_MANAGER))

	def test_administrator_can_create(self):
		self.assertTrue(has_permission(make_notification(USER1), "create", "Administrator"))

	def test_regular_user_cannot_create(self):
		self.assertFalse(has_permission(make_notification(USER1), "create", USER1))

	def test_regular_user_cannot_create_notification_without_to_user(self):
		self.assertFalse(has_permission(make_notification(None), "create", USER1))

	def test_recipient_can_read_own_notification(self):
		self.assertTrue(has_permission(make_notification(USER1), "read", USER1))

	def test_user_cannot_read_others_notification(self):
		self.assertFalse(has_permission(make_notification(USER2), "read", USER1))

	def test_notification_without_to_user_is_readable(self):
		self.assertTrue(has_permission(make_notification(None), "read", USER1))


def make_notification(to_user):
	doc = frappe.get_doc({"doctype": "CRM Notification", "to_user": to_user, "type": "Mention"})
	doc.flags.ignore_mandatory = True
	return doc


class TestNotifyUser(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_an_identical_notification_is_not_inserted_twice(self):
		"""The guard passed the insert dict, "doctype" key and all, as its filter:
		tabCRM Notification has no such column, the lookup's error was swallowed
		as "not found", and every repeat was inserted."""
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Dedup Probe"}).insert(
			ignore_permissions=True
		)
		payload = {
			"owner": "Administrator",
			"assigned_to": USER1,
			"notification_type": "Mention",
			"message": "<p>dedup probe</p>",
			"notification_text": "dedup probe",
			"reference_doctype": "CRM Lead",
			"reference_docname": lead.name,
			"redirect_to_doctype": "CRM Lead",
			"redirect_to_docname": lead.name,
		}

		notify_user(payload)
		notify_user(payload)

		self.assertEqual(frappe.db.count("CRM Notification", {"notification_type_doc": lead.name}), 1)

	def test_a_different_message_is_still_delivered(self):
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Dedup Control"}).insert(
			ignore_permissions=True
		)
		payload = {
			"owner": "Administrator",
			"assigned_to": USER1,
			"notification_type": "Mention",
			"message": "<p>first</p>",
			"reference_doctype": "CRM Lead",
			"reference_docname": lead.name,
			"redirect_to_doctype": "CRM Lead",
			"redirect_to_docname": lead.name,
		}

		notify_user(payload)
		notify_user({**payload, "message": "<p>second</p>"})

		self.assertEqual(frappe.db.count("CRM Notification", {"notification_type_doc": lead.name}), 2)
