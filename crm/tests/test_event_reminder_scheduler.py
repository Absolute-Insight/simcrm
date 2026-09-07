# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The reminder sweep runs as Administrator and must still find everyone's events.

The selection query used to filter on ``frappe.session.user`` as the event's owner
or a participant. Under the scheduler that user is Administrator, so a rep's
"Site visit" with a 30-minute reminder was never selected and neither the email
nor the in-app popup fired -- for anyone but Administrator, ever. The audience of
each reminder is decided per event by ``_notification_audience``; the sweep
itself has to be site-wide.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from crm.api.event import _process_event_notifications_by_interval

REP = "reminder-rep@crmtest.test"


class ReminderSweepTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", REP):
			user = frappe.get_doc(
				{"doctype": "User", "email": REP, "first_name": "Reminder Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		self.events = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in self.events:
			frappe.delete_doc("Event", name, force=True, ignore_permissions=True)
		super().tearDown()

	def make_event(self, owner: str, subject: str):
		frappe.set_user(owner)
		starts = now_datetime() + timedelta(minutes=30)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": subject,
				"event_type": "Private",
				"starts_on": starts,
				"ends_on": starts + timedelta(hours=1),
				# a custom reminder 30 minutes before, so the trigger time is now
				"notifications": [{"type": "Notification", "before": 30, "interval": "minutes"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user("Administrator")
		self.events.append(event.name)
		return event

	def test_a_reps_event_is_swept_when_the_scheduler_runs_as_administrator(self):
		mine = self.make_event(REP, "Site visit: reminder sweep")
		admins = self.make_event("Administrator", "Board meeting: reminder sweep")

		frappe.set_user("Administrator")
		with patch("crm.api.event._send_system_notification") as send:
			_process_event_notifications_by_interval("minutes")

		swept = {call.args[0].get("event_name") for call in send.call_args_list}
		self.assertIn(mine.name, swept, "the rep's event was not selected by the sweep")
		self.assertIn(admins.name, swept)

	def test_the_reminder_goes_to_the_events_owner_not_to_whoever_runs_the_job(self):
		mine = self.make_event(REP, "Customer call: reminder audience")

		frappe.set_user("Administrator")
		with patch.object(frappe, "publish_realtime") as publish:
			_process_event_notifications_by_interval("minutes")

		for_mine = [c for c in publish.call_args_list if c.args[1].get("event_name") == mine.name]
		self.assertTrue(for_mine, "no realtime reminder was published for the rep's event")
		self.assertEqual({c.kwargs.get("user") for c in for_mine}, {REP})
