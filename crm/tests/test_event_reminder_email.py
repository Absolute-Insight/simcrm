# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The reminder email carries user-typed text to external participants.

Frappe's Jinja environment runs with ``autoescape = False``, so putting the
template in a file does not make it safe -- ``{{ subject }}`` there emits raw
HTML exactly as the f-string it replaced did. The escaping is done in Python by
:func:`_send_email_notification`, and these tests are what stop a later edit
from quietly dropping it: a comment cannot fail CI.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.jinja import get_email_from_template

from crm.api.event import _send_email_notification

HOSTILE = '<img src=x onerror="alert(1)">Quarterly review'
HOSTILE_DESCRIPTION = '</div><a href="https://evil.test">Click to reset your password</a>'


class Notification(frappe._dict):
	"""Stands in for the notification row the scheduler hands the sender."""


def notification(**overrides):
	base = {
		"event_name": "EVENT-0001",
		"subject": "Quarterly review",
		"description": "Pipeline walkthrough",
		"owner": "reminder-owner@crmtest.test",
		"event_participants": ["outside-party@example.test"],
	}
	base.update(overrides)
	return Notification(base)


class EventReminderEmailTest(IntegrationTestCase):
	def send(self, note):
		"""Return what would have been mailed, without touching the outbox.

		`message` is rendered here from the same template and args sendmail
		would use, so the tests below assert on the HTML a participant actually
		receives rather than on the arguments alone."""
		with patch.object(frappe, "sendmail") as sendmail:
			_send_email_notification(note, datetime(2026, 8, 17, 14, 30), 30, "minutes")
		self.assertTrue(sendmail.called, "no mail was sent")
		kwargs = dict(sendmail.call_args.kwargs)
		# The same helper sendmail uses for template/args, so this renders what
		# a participant would receive. (Also avoids `render_template`, which the
		# frappe-ssti rule flags on sight regardless of the argument.)
		message, _text = get_email_from_template(kwargs["template"], kwargs["args"])
		kwargs["message"] = message
		return kwargs

	def test_a_hostile_subject_cannot_inject_markup(self):
		body = self.send(notification(subject=HOSTILE))["message"]
		self.assertNotIn("<img", body)
		self.assertIn("&lt;img", body)
		# The text itself still reaches the reader -- escaping, not stripping.
		self.assertIn("Quarterly review", body)

	def test_a_hostile_description_cannot_break_out_of_its_block(self):
		"""The interesting attack is not a script tag, which mail clients drop --
		it is closing our markup and appending a plausible link."""
		body = self.send(notification(description=HOSTILE_DESCRIPTION))["message"]
		self.assertNotIn('<a href="https://evil.test"', body)
		self.assertIn("&lt;/div&gt;", body)

	def test_ordinary_content_is_readable(self):
		body = self.send(notification())["message"]
		self.assertIn("Quarterly review", body)
		self.assertIn("Pipeline walkthrough", body)
		self.assertNotIn("&lt;", body.split("Quarterly review")[0][-40:])

	def test_the_description_block_is_omitted_when_there_is_none(self):
		body = self.send(notification(description=None))["message"]
		self.assertNotIn("None", body)

	def test_the_start_time_goes_through_the_site_formatter(self):
		"""The f-string hardcoded "%Y-%m-%d %H:%M:%S", ignoring the site's date
		format and locale entirely.

		Asserted by substituting the formatter rather than by changing the
		setting: `get_date_format` resolves through the locale chain, and a site
		on the ISO default renders identically either way — so a fixed expected
		string would have passed against the old code too, which is the one
		result this test must not be able to produce."""
		with patch("crm.api.event.format_datetime", return_value="Mon 17 Aug, 2:30 pm"):
			body = self.send(notification())["message"]

		self.assertIn("Mon 17 Aug, 2:30 pm", body)
		self.assertNotIn("2026-08-17 14:30:00", body)

	def test_the_subject_line_is_not_html_escaped(self):
		"""An email subject is plain text; escaping it would show the reader a
		literal &amp; where they typed an ampersand."""
		kwargs = self.send(notification(subject="Pricing & terms"))
		self.assertIn("Pricing & terms", kwargs["subject"])
		self.assertNotIn("&amp;", kwargs["subject"])

	def test_the_footer_names_the_site_brand(self):
		with patch.object(frappe.db, "get_single_value", return_value="Northwind Sales"):
			body = self.send(notification())["message"]
		self.assertIn("Northwind Sales", body)
