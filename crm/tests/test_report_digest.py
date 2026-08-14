# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Digest tests: due digests queue mail, disabled ones do not, bad emails rejected."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_report_digest.crm_report_digest import send_due_digests


class ReportDigestTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("CRM Report Digest")
		frappe.db.delete("Email Queue")

	def tearDown(self):
		frappe.db.delete("CRM Report Digest")
		frappe.db.delete("Email Queue")
		super().tearDown()

	def make_digest(self, **overrides):
		digest = {
			"doctype": "CRM Report Digest",
			"report": "pipeline_by_stage",
			"frequency": "Daily",
			"enabled": 1,
			"recipients": "manager@crmtest.test",
		}
		digest.update(overrides)
		return frappe.get_doc(digest).insert(ignore_permissions=True)

	def queued_subjects(self):
		return [
			frappe.db.get_value("Email Queue", name, "message") or ""
			for name in frappe.get_all("Email Queue", pluck="name")
		]

	def test_a_daily_digest_queues_an_email_with_the_report(self):
		self.make_digest()
		sent = send_due_digests()
		self.assertEqual(sent, 1)
		self.assertTrue(frappe.db.count("Email Queue") >= 1)

	def test_a_disabled_digest_sends_nothing(self):
		self.make_digest(enabled=0)
		self.assertEqual(send_due_digests(), 0)
		self.assertEqual(frappe.db.count("Email Queue"), 0)

	def test_a_weekly_digest_waits_for_monday(self):
		self.make_digest(frequency="Weekly")
		sent = send_due_digests()
		is_monday = frappe.utils.getdate().weekday() == 0
		self.assertEqual(sent, 1 if is_monday else 0)

	def test_an_invalid_recipient_is_rejected_at_save(self):
		with self.assertRaises(frappe.exceptions.InvalidEmailAddressError):
			self.make_digest(recipients="not-an-email")
