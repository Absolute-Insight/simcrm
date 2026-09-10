# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""The Exotel webhook token is a secret, not a setting.

``handle_request`` is an unauthenticated endpoint and this token is the only
thing in front of it, yet it was a plain Data field: it sat in ``tabSingles`` in
clear and came back from ``frappe.client.get_single_value`` for anyone who could
read the singleton. It is a Password field now, like the Acumatica one.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import remove_encrypted_password, set_encrypted_password

from crm.integrations.exotel.handler import _webhook_verify_token

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]

SINGLE = "CRM Exotel Settings"
FIELD = "webhook_verify_token"


class IntegrationTestCRMExotelSettings(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.original = frappe.get_doc(SINGLE).get_password(FIELD, raise_exception=False)
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(self.write_token, self.original or "")

	@staticmethod
	def write_token(value: str):
		"""Straight into the store, which is how the site's own value is put back.

		The form's ``mandatory_depends_on`` rules are not what these tests are
		about, and they would refuse to blank the field on a site with Exotel on.
		"""
		if value:
			set_encrypted_password(SINGLE, SINGLE, value, FIELD)
			frappe.db.set_single_value(SINGLE, FIELD, "*" * len(value))
		else:
			remove_encrypted_password(SINGLE, SINGLE, FIELD)
			frappe.db.set_single_value(SINGLE, FIELD, "")
		frappe.clear_document_cache(SINGLE, SINGLE)

	def save_token(self, value: str):
		"""Through the document, so the encryption on save is what is tested."""
		settings = frappe.get_doc(SINGLE)
		settings.webhook_verify_token = value
		settings.flags.ignore_validate = True
		settings.save(ignore_permissions=True)
		frappe.clear_document_cache(SINGLE, SINGLE)

	def test_the_token_field_is_a_password(self):
		self.assertEqual(frappe.get_meta(SINGLE).get_field(FIELD).fieldtype, "Password")

	def test_saving_the_token_leaves_no_plaintext_in_the_singles_table(self):
		self.save_token("plain-token-for-test")
		self.assertNotEqual(frappe.db.get_single_value(SINGLE, FIELD), "plain-token-for-test")

	def test_the_webhook_verifies_against_the_token_that_was_saved(self):
		self.save_token("plain-token-for-test")
		self.assertEqual(_webhook_verify_token(), "plain-token-for-test")

	def test_no_token_reads_as_empty_rather_than_raising(self):
		self.write_token("")
		self.assertFalse(_webhook_verify_token())
