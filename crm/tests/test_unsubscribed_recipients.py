# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The composer's check matches what frappe's mail queue will silently drop."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api import MAX_UNSUBSCRIBE_CHECK, UNSUBSCRIBE_RATE_SCOPE, get_unsubscribed_emails
from crm.tests.test_row_permissions import ensure_rep
from crm.utils import user_rate_key

ALICE = "unsub-alice@crmtest.test"
BOB = "unsub-bob@crmtest.test"
OUTSIDER = "unsub-outsider@crmtest.test"


def make_lead(owner=None):
	return frappe.get_doc({"doctype": "CRM Lead", "first_name": "Unsubscribed", "lead_owner": owner}).insert(
		ignore_permissions=True
	)


def unsubscribe(email, **kwargs):
	frappe.get_doc({"doctype": "Email Unsubscribe", "email": email, **kwargs}).insert(ignore_permissions=True)


class TestUnsubscribedRecipients(IntegrationTestCase):
	def setUp(self):
		ensure_rep(ALICE, "Alice")
		ensure_rep(BOB, "Bob")
		self.lead = make_lead()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def check(self, emails, lead=None):
		return get_unsubscribed_emails(emails, "CRM Lead", (lead or self.lead).name)

	def test_a_global_unsubscribe_is_reported(self):
		unsubscribe("gone@example.com", global_unsubscribe=1)

		self.assertEqual(self.check(["gone@example.com", "here@example.com"]), ["gone@example.com"])

	def test_an_unsubscribe_from_this_record_is_reported(self):
		unsubscribe("gone@example.com", reference_doctype="CRM Lead", reference_name=self.lead.name)

		self.assertEqual(self.check(["gone@example.com"]), ["gone@example.com"])

	def test_an_unsubscribe_from_another_record_is_not_reported(self):
		unsubscribe("gone@example.com", reference_doctype="CRM Lead", reference_name=make_lead().name)

		self.assertEqual(self.check(["gone@example.com"]), [])

	def test_no_recipients_reports_nothing(self):
		self.assertEqual(self.check([]), [])

	def test_a_rep_who_cannot_read_the_record_is_refused(self):
		bobs_lead = make_lead(BOB)
		frappe.set_user(ALICE)

		with self.assertRaises(frappe.PermissionError):
			self.check(["gone@example.com"], bobs_lead)

	def test_the_owner_of_the_record_may_ask(self):
		unsubscribe("gone@example.com", global_unsubscribe=1)
		lead = make_lead(ALICE)
		frappe.set_user(ALICE)

		self.assertEqual(self.check(["gone@example.com"], lead), ["gone@example.com"])

	def test_the_list_of_addresses_is_bounded(self):
		unsubscribe("inside@example.com", global_unsubscribe=1)
		unsubscribe("past-the-cap@example.com", global_unsubscribe=1)
		filler = [f"person{index}@example.com" for index in range(MAX_UNSUBSCRIBE_CHECK)]

		reported = self.check(["inside@example.com", *filler, "past-the-cap@example.com"])

		self.assertEqual(reported, ["inside@example.com"])

	def test_a_user_with_no_crm_role_is_refused(self):
		if not frappe.db.exists("User", OUTSIDER):
			frappe.get_doc(
				{"doctype": "User", "email": OUTSIDER, "first_name": "Outsider", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(OUTSIDER)

		with self.assertRaises(frappe.PermissionError):
			self.check(["gone@example.com"])

	def test_an_empty_name_is_refused(self):
		unsubscribe("gone@example.com", global_unsubscribe=1)
		frappe.set_user(ALICE)

		with self.assertRaises(frappe.PermissionError):
			get_unsubscribed_emails(["gone@example.com"], "CRM Lead", "")

	def test_a_doctype_the_composer_does_not_run_on_is_refused(self):
		unsubscribe("gone@example.com", global_unsubscribe=1)
		frappe.set_user(ALICE)

		with self.assertRaises(frappe.PermissionError):
			get_unsubscribed_emails(["gone@example.com"], "Contact", "")

	def test_a_user_cannot_probe_addresses_without_limit(self):
		lead = make_lead(ALICE)
		frappe.set_user(ALICE)
		frappe.flags.enforce_user_rate_limits = True
		self.addCleanup(setattr, frappe.flags, "enforce_user_rate_limits", False)
		frappe.cache().delete(user_rate_key(UNSUBSCRIBE_RATE_SCOPE))

		with patch("crm.api.UNSUBSCRIBE_RATE_LIMIT", 1):
			self.check(["first@example.com"], lead)
			with self.assertRaises(frappe.TooManyRequestsError):
				self.check(["second@example.com"], lead)
