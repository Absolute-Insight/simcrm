# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Digest tests: due digests queue mail, disabled ones do not, and what goes out
is scoped to the recipient, escaped, and addressed to someone allowed to read it.

Nothing here truncates Email Queue or CRM Report Digest — this suite shares a
site with the app's own mail — so every delete names the rows it created.
"""

from __future__ import annotations

from email import message_from_string
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.api.reports import REPORTS, get_report
from crm.fcrm.doctype.crm_report_digest import crm_report_digest
from crm.fcrm.doctype.crm_report_digest.crm_report_digest import (
	TD_STYLE,
	_render_digest,
	send_due_digests,
)

RECIPIENT = "digest-manager@crmtest.test"


class ReportDigestTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", RECIPIENT):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": RECIPIENT,
					"first_name": "Digest Manager",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Sales Manager")
		self.digests: list[str] = []
		self.clear_mail()

	def tearDown(self):
		for name in self.digests:
			frappe.delete_doc("CRM Report Digest", name, force=True, ignore_permissions=True)
		self.clear_mail()
		super().tearDown()

	def clear_mail(self):
		frappe.db.delete("Email Queue", {"reference_doctype": "CRM Report Digest"})

	def make_digest(self, **overrides):
		digest = {
			"doctype": "CRM Report Digest",
			"report": "pipeline_by_stage",
			"frequency": "Daily",
			"enabled": 1,
			"recipients": RECIPIENT,
		}
		digest.update(overrides)
		doc = frappe.get_doc(digest).insert(ignore_permissions=True)
		self.digests.append(doc.name)
		return doc

	def queued_messages(self):
		"""The HTML body of every queued digest, decoded out of the MIME envelope."""
		messages = []
		for name in frappe.get_all(
			"Email Queue", filters={"reference_doctype": "CRM Report Digest"}, pluck="name"
		):
			raw = frappe.db.get_value("Email Queue", name, "message") or ""
			html = [
				part.get_payload(decode=True).decode("utf-8", "replace")
				for part in message_from_string(raw).walk()
				if part.get_content_type() == "text/html"
			]
			messages.append(html[0] if html else raw)
		return messages

	def test_a_daily_digest_queues_an_email_with_the_report(self):
		open_status = frappe.get_all("CRM Deal Status", filters={"type": "Open"}, pluck="name")
		if not open_status:
			self.skipTest("site has no Open deal status")
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Digest Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": org,
				"deal_owner": RECIPIENT,
				"status": open_status[0],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True)

		self.make_digest()
		self.assertEqual(send_due_digests(), 1)

		messages = self.queued_messages()
		self.assertEqual(len(messages), 1)
		self.assertIn("Pipeline by stage", messages[0])
		self.assertIn(open_status[0], messages[0])

	def test_a_disabled_digest_sends_nothing(self):
		self.make_digest(enabled=0)
		self.assertEqual(send_due_digests(), 0)
		self.assertEqual(self.queued_messages(), [])

	def on_day(self, day: str):
		"""Pin "today" for the scheduler without pinning it for everything else —
		only the bare ``getdate()`` the weekly check makes is answered."""
		real = frappe.utils.getdate

		def fixed(*args, **kwargs):
			return real(day) if not args and not kwargs else real(*args, **kwargs)

		return patch.object(crm_report_digest.frappe.utils, "getdate", side_effect=fixed)

	def test_a_weekly_digest_fires_on_a_monday(self):
		self.make_digest(frequency="Weekly")
		with self.on_day("2026-08-10"):
			self.assertEqual(send_due_digests(), 1)

	def test_a_weekly_digest_waits_on_any_other_day(self):
		self.make_digest(frequency="Weekly")
		with self.on_day("2026-08-12"):
			self.assertEqual(send_due_digests(), 0)

	def test_an_invalid_recipient_is_rejected_at_save(self):
		with self.assertRaises(frappe.exceptions.InvalidEmailAddressError):
			self.make_digest(recipients="not-an-email")

	def test_a_digest_is_not_a_mailing_list(self):
		"""Every recipient is a full report render under their own session; the
		count is refused before any address is validated."""
		from crm.fcrm.doctype.crm_report_digest.crm_report_digest import MAX_RECIPIENTS

		too_many = ", ".join(f"rep{i}@crmtest.test" for i in range(MAX_RECIPIENTS + 1))
		with self.assertRaisesRegex(frappe.ValidationError, "at most"):
			self.make_digest(recipients=too_many)

	def test_an_outside_address_cannot_be_mailed_deal_values(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_digest(recipients="stranger@example.com")

	def test_a_user_without_a_crm_role_cannot_be_mailed_deal_values(self):
		outsider = "digest-outsider@crmtest.test"
		if not frappe.db.exists("User", outsider):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": outsider,
					"first_name": "Digest Outsider",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self.make_digest(recipients=outsider)

	def test_a_stage_name_reaches_the_email_escaped(self):
		"""Frappe forbids angle brackets in a document name, so the worst a stage
		name can carry is an ampersand — it still has to arrive as markup-safe."""
		status = frappe.get_doc(
			{
				"doctype": "CRM Deal Status",
				"deal_status": "Bids & Tenders",
				"type": "Open",
				"color": "gray",
				"position": 99,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Deal Status", status.name, force=True)
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Digest Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": org,
				"deal_owner": RECIPIENT,
				"status": status.name,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True)

		self.make_digest()
		send_due_digests()

		message = self.queued_messages()[0]
		self.assertIn("Bids &amp; Tenders", message)

	def test_one_broken_digest_does_not_stop_the_rest(self):
		"""A single failure used to abort the scheduler entry, so every digest
		queued behind it silently never went out."""
		self.make_digest()
		self.make_digest()
		real_sendmail = crm_report_digest.frappe.sendmail
		calls = []

		def explode_once(*args, **kwargs):
			calls.append(kwargs)
			if len(calls) == 1:
				raise ValueError("mail server said no")
			return real_sendmail(*args, **kwargs)

		with patch.object(crm_report_digest.frappe, "sendmail", side_effect=explode_once):
			self.assertEqual(send_due_digests(), 1)
		self.assertEqual(len(calls), 2)


class SchedulableReportsTest(IntegrationTestCase):
	"""Every report the site publishes must be schedulable, and only those.

	The Select field and ``REPORTS`` are two lists of the same thing, and they
	had already drifted: ``quota_attainment_by_rep`` shipped as a report and was
	never added to the Select, so the one report a sales manager most wants
	mailed to them could not be scheduled at all. Nothing failed -- the field
	simply did not offer it.
	"""

	def options(self) -> list[str]:
		field = frappe.get_meta("CRM Report Digest").get_field("report")
		return [option for option in (field.options or "").split("\n") if option]

	def test_the_select_offers_exactly_the_published_reports(self):
		self.assertEqual(sorted(self.options()), sorted(REPORTS))

	def test_every_option_actually_renders(self):
		for name in self.options():
			with self.subTest(report=name):
				report = get_report(name, "2026-01-01", "2026-01-31")
				self.assertIn("columns", report)
				_render_digest(report, "2026-01-01", "2026-01-31")

	def test_a_digest_naming_a_report_the_site_does_not_publish_is_refused(self):
		"""The send loop skips an unknown key silently, so a typo would cost a
		digest that never arrives and never complains."""
		doc = frappe.get_doc(
			{
				"doctype": "CRM Report Digest",
				"report": "pipeline_by_stage",
				"frequency": "Daily",
				"enabled": 1,
				"recipients": RECIPIENT,
			}
		)
		doc.report = "a_report_that_was_withdrawn"
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)


class RenderDigestTest(UnitTestCase):
	"""The renderer is a pure function, so the hostile input a doctype name would
	never accept can be put through it directly."""

	def report(self, **overrides):
		report = {
			"title": "Pipeline by stage",
			"columns": [{"key": "stage", "label": "Stage"}],
			"rows": [{"stage": "Qualification"}],
		}
		report.update(overrides)
		return report

	def test_a_cell_value_is_escaped(self):
		html = _render_digest(
			self.report(rows=[{"stage": "<script>alert(1)</script>"}]), "2026-01-01", "2026-01-02"
		)
		self.assertIn("&lt;script&gt;", html)
		self.assertNotIn("<script>alert(1)</script>", html)

	def test_a_column_label_is_escaped(self):
		html = _render_digest(
			self.report(columns=[{"key": "stage", "label": "<b>Stage</b>"}]), "2026-01-01", "2026-01-02"
		)
		self.assertIn("&lt;b&gt;Stage&lt;/b&gt;", html)

	def test_the_title_and_the_dates_are_escaped(self):
		html = _render_digest(self.report(title="<i>Pipeline</i>"), "<x>", "2026-01-02")
		self.assertIn("&lt;i&gt;Pipeline&lt;/i&gt;", html)
		self.assertIn("&lt;x&gt;", html)

	def test_a_missing_value_renders_blank(self):
		"""A null cell used to reach the email as the literal word "None"."""
		html = _render_digest(self.report(rows=[{"stage": None}]), "2026-01-01", "2026-01-02")
		self.assertIn(f'<td style="{TD_STYLE}"></td>', html)
		self.assertNotIn("None", html)

	def test_a_zero_still_renders(self):
		"""Blanking None must not blank the falsy values that are real answers."""
		html = _render_digest(self.report(rows=[{"stage": 0}]), "2026-01-01", "2026-01-02")
		self.assertIn(f'<td style="{TD_STYLE}">0</td>', html)
