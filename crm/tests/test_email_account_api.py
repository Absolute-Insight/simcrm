# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.email.doctype.email_account.email_account import EmailAccount
from frappe.tests import IntegrationTestCase

from crm.api.settings import create_email_account


class TestCreateEmailAccount(IntegrationTestCase):
	"""create_email_account must persist the lead-capture toggle and never wire
	frappe-core's append_to ingestion, which would create a CRM Lead from every
	incoming email regardless of the toggle."""

	ACCOUNT_NAME = "Toggle Check"

	def tearDown(self):
		frappe.db.rollback()

	def _create(self, **overrides):
		data = {
			"service": "GMail",
			"email_account_name": self.ACCOUNT_NAME,
			"email_id": "toggle-check@example.com",
			"password": "app-password",
			"enable_incoming": 1,
			**overrides,
		}
		with (
			patch.object(EmailAccount, "get_incoming_server", return_value=None),
			patch.object(EmailAccount, "validate_imap_folders_exist", return_value=None),
			patch.object(EmailAccount, "validate_smtp_conn", return_value=True),
		):
			create_email_account(data)
		return frappe.get_doc("Email Account", self.ACCOUNT_NAME)

	def test_toggle_on_is_persisted_without_append_to(self):
		doc = self._create(create_lead_from_incoming_email=True)
		self.assertEqual(doc.create_lead_from_incoming_email, 1)
		self.assertFalse(doc.append_to)
		folders = [(f.folder_name, f.append_to) for f in doc.imap_folder]
		self.assertEqual(folders, [("INBOX", None)])

	def test_toggle_absent_defaults_off(self):
		doc = self._create()
		self.assertEqual(doc.create_lead_from_incoming_email, 0)
		self.assertFalse(doc.append_to)
		self.assertFalse([f for f in doc.imap_folder if f.append_to])
