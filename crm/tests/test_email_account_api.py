# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.email.doctype.email_account.email_account import EmailAccount
from frappe.tests import IntegrationTestCase

from crm.api.settings import create_email_account, custom_service_config


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


class TestCustomServiceConfig(IntegrationTestCase):
	def test_defaults_are_ssl_imap_and_starttls_smtp(self):
		config = custom_service_config({"email_server": "imap.ionos.com", "smtp_server": "smtp.ionos.com"})
		self.assertEqual(
			config,
			{
				"email_server": "imap.ionos.com",
				"use_ssl": 1,
				"use_starttls": 0,
				"smtp_server": "smtp.ionos.com",
				"smtp_port": 587,
				"use_ssl_for_outgoing": 0,
				"use_tls": 1,
			},
		)

	def test_smtp_port_465_switches_outgoing_to_ssl(self):
		config = custom_service_config(
			{"email_server": "imap.x.com", "smtp_server": "smtp.x.com", "smtp_port": "465"}
		)
		self.assertEqual(config["smtp_port"], 465)
		self.assertEqual(config["use_ssl_for_outgoing"], 1)
		self.assertEqual(config["use_tls"], 0)

	def test_ssl_off_enables_starttls_for_incoming(self):
		config = custom_service_config(
			{"email_server": "imap.x.com", "smtp_server": "smtp.x.com", "use_ssl": 0}
		)
		self.assertEqual(config["use_ssl"], 0)
		self.assertEqual(config["use_starttls"], 1)

	def test_garbage_port_falls_back_to_587(self):
		config = custom_service_config(
			{"email_server": "imap.x.com", "smtp_server": "smtp.x.com", "smtp_port": "abc"}
		)
		self.assertEqual(config["smtp_port"], 587)

	def test_missing_server_returns_none(self):
		self.assertIsNone(custom_service_config({"smtp_server": "smtp.x.com"}))
		self.assertIsNone(custom_service_config({"email_server": "imap.x.com"}))
		self.assertIsNone(custom_service_config({"email_server": "  ", "smtp_server": "smtp.x.com"}))


class TestCreateCustomEmailAccount(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_custom_account_is_created_with_form_servers(self):
		data = {
			"service": "Custom",
			"email_account_name": "Custom IONOS",
			"email_id": "vectora@example.com",
			"password": "mailbox-password",
			"email_server": "imap.ionos.com",
			"smtp_server": "smtp.ionos.com",
			"smtp_port": "587",
			"use_ssl": 1,
			"enable_incoming": 1,
			"enable_outgoing": 1,
		}
		with (
			patch.object(EmailAccount, "get_incoming_server", return_value=None),
			patch.object(EmailAccount, "validate_imap_folders_exist", return_value=None),
			patch.object(EmailAccount, "validate_smtp_conn", return_value=True),
		):
			create_email_account(data)
		doc = frappe.get_doc("Email Account", "Custom IONOS")
		self.assertEqual(doc.service, "")
		self.assertEqual(doc.email_server, "imap.ionos.com")
		self.assertEqual(doc.use_ssl, 1)
		self.assertEqual(doc.smtp_server, "smtp.ionos.com")
		self.assertEqual(int(doc.smtp_port), 587)
		self.assertEqual(doc.use_tls, 1)

	def test_custom_account_without_servers_throws(self):
		data = {
			"service": "Custom",
			"email_account_name": "Broken Custom",
			"email_id": "x@example.com",
			"password": "pw",
		}
		self.assertRaises(frappe.ValidationError, create_email_account, data)
