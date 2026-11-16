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

from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from crm.api.event import trigger_offset_event_notifications as trigger_event_notifications

REP = "reminder-rep@crmtest.test"
# sent-ledger rows this module may delete: only those made since it was imported,
# never the live record of a site the suite is pointed at
_STARTED = {}


def setUpModule():
	_STARTED["at"] = now_datetime() - timedelta(seconds=1)


def ensure_rep():
	if not frappe.db.exists("User", REP):
		user = frappe.get_doc(
			{"doctype": "User", "email": REP, "first_name": "Reminder Rep", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


def forget_sent_reminders():
	"""The sent ledger is written on its own connection, so it outlives a
	rolled-back test, and event names are reused once their series is rolled
	back: each test starts from a clean one."""
	from crm.utils.autonomous import autonomous_db

	with autonomous_db() as db:
		db.sql("delete from `tabCRM Event Reminder Sent` where creation >= %s", (_STARTED["at"],))


class ReminderSweepTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_rep()
		forget_sent_reminders()
		self.events = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in self.events:
			frappe.delete_doc("Event", name, force=True, ignore_permissions=True)
		forget_sent_reminders()
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
			trigger_event_notifications()

		swept = {call.args[0].get("event_name") for call in send.call_args_list}
		self.assertIn(mine.name, swept, "the rep's event was not selected by the sweep")
		self.assertIn(admins.name, swept)

	def test_the_reminder_goes_to_the_events_owner_not_to_whoever_runs_the_job(self):
		mine = self.make_event(REP, "Customer call: reminder audience")

		frappe.set_user("Administrator")
		with patch.object(frappe, "publish_realtime") as publish:
			trigger_event_notifications()

		for_mine = [c for c in publish.call_args_list if c.args[1].get("event_name") == mine.name]
		self.assertTrue(for_mine, "no realtime reminder was published for the rep's event")
		self.assertEqual({c.kwargs.get("user") for c in for_mine}, {REP})


# When frappe runs each scheduler frequency: its CRON_MAP at the default
# scheduler_interval of 240 s ("all" is */4).
SCHEDULE = {
	"all": lambda t: t.minute % 4 == 0,
	"hourly": lambda t: t.minute == 0,
	"daily": lambda t: t.hour == 0 and t.minute == 0,
	"weekly": lambda t: t.weekday() == 6 and t.hour == 0 and t.minute == 0,
}


def run_scheduler(start: datetime, end: datetime, clock: dict):
	"""Run every event-reminder job crm/hooks.py schedules, on the cadence frappe
	would run it, minute by minute from `start` to `end` on the site clock, keeping
	the current minute in `clock["now"]`.

	Read from the hooks rather than naming the functions, so the test measures
	what production runs: a reminder swept by two jobs is sent by both."""
	scheduled = frappe.get_hooks("scheduler_events", app_name="crm")
	jobs = [
		(SCHEDULE[frequency], frappe.get_attr(method))
		for frequency, methods in scheduled.items()
		if frequency in SCHEDULE
		for method in methods
		if method.startswith("crm.api.event.")
	]
	clock["now"] = start
	while clock["now"] <= end:
		due = [job for runs_at, job in jobs if runs_at(clock["now"])]
		if due:
			with patch("crm.api.event.now_datetime", return_value=clock["now"]):
				for job in due:
					job()
		clock["now"] += timedelta(minutes=1)


class ReminderCadenceTest(IntegrationTestCase):
	"""Each reminder is delivered exactly once, near the time it was set for.

	Nothing recorded that a reminder had gone out. The "all" job swept minutes
	and hours every 4 minutes, "hourly" swept hours again, every match within
	+/-5 min or +/-1 h of the trigger was sent, and an event in progress widened
	that to the whole meeting: 17 emails for "10 minutes before", 48 for "1 hour
	before", to the owner and every external participant. The "days" window was
	+/-8 h around a sweep that only ran at midnight, so a business-hours meeting's
	"1 day before" never fired at all."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_rep()
		forget_sent_reminders()
		self.events = []
		self.errors = []
		# Far enough ahead that no real sweep could have touched it, on a fixed hour.
		self.day = (now_datetime() + timedelta(days=10)).replace(hour=0, minute=0, second=0, microsecond=0)
		settings = frappe.get_single("FCRM Settings")
		self.global_reminders = {
			"event_notifications": [row.as_dict() for row in settings.event_notifications],
			"all_day_event_notifications": [row.as_dict() for row in settings.all_day_event_notifications],
		}
		self.set_global_reminders([], [])

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in self.events:
			frappe.delete_doc("Event", name, force=True, ignore_permissions=True)
		settings = frappe.get_single("FCRM Settings")
		for table, rows in self.global_reminders.items():
			settings.set(table, [{k: row[k] for k in ("type", "before", "interval", "time")} for row in rows])
		settings.flags.ignore_permissions = True
		settings.save()
		forget_sent_reminders()
		super().tearDown()

	def set_global_reminders(self, regular, all_day):
		settings = frappe.get_single("FCRM Settings")
		settings.set("event_notifications", regular)
		settings.set("all_day_event_notifications", all_day)
		settings.flags.ignore_permissions = True
		settings.save()

	def make_event(self, starts_on, notifications=(), all_day=0):
		frappe.set_user(REP)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Site visit: reminder cadence",
				"event_type": "Private",
				"starts_on": starts_on,
				"ends_on": starts_on.replace(hour=23, minute=59, second=59)
				if all_day
				else starts_on + timedelta(hours=1),
				"all_day": all_day,
				"notifications": list(notifications),
			}
		).insert(ignore_permissions=True)
		frappe.set_user("Administrator")
		self.events.append(event.name)
		return event

	def sweep(self, start, end):
		"""Run the scheduler and return what it sent for this test's events, as
		(emails, popups): one (clock, event name, label) per send, not per recipient."""
		emails, popups, clock = [], [], {}

		def sendmail(**kwargs):
			emails.append((clock["now"], kwargs["reference_name"], kwargs["args"]["time_remaining"]))

		def publish(event, message, user=None, **kwargs):
			if user == REP:
				popups.append((clock["now"], message["event_name"], message.get("before_value")))

		with (
			patch.object(frappe, "sendmail", side_effect=sendmail),
			patch.object(frappe, "publish_realtime", side_effect=publish),
			patch.object(frappe, "log_error", side_effect=lambda *a, **k: self.errors.append(a)),
		):
			run_scheduler(start, end, clock)

		mine = set(self.events)
		return [e for e in emails if e[1] in mine], [p for p in popups if p[1] in mine]

	def test_each_email_reminder_is_sent_once(self):
		starts = self.day.replace(hour=10)
		event = self.make_event(
			starts,
			[
				{"type": "Email", "before": 10, "interval": "minutes"},
				{"type": "Email", "before": 1, "interval": "hours"},
			],
		)

		emails, _popups = self.sweep(starts - timedelta(hours=3), starts + timedelta(hours=2))

		labels = [label for _clock, _name, label in emails]
		self.assertEqual(labels.count("10 minute(s)"), 1, emails)
		self.assertEqual(labels.count("1 hour(s)"), 1, emails)
		sent_at = {label: clock for clock, _name, label in emails}
		# within one 4-minute tick of the time it was set for, never early
		self.assertTrue(
			starts - timedelta(minutes=10) <= sent_at["10 minute(s)"] < starts - timedelta(minutes=6)
		)
		self.assertTrue(starts - timedelta(hours=1) <= sent_at["1 hour(s)"] < starts - timedelta(minutes=56))
		self.assertEqual({name for _clock, name, _label in emails}, {event.name})
		self.assertEqual(self.errors, [])

	def test_a_day_before_reminder_fires_for_a_business_hours_meeting(self):
		starts = self.day.replace(hour=10)
		self.make_event(starts, [{"type": "Email", "before": 1, "interval": "days"}])

		emails, _popups = self.sweep(starts - timedelta(days=2), starts + timedelta(hours=1))

		self.assertEqual(len(emails), 1, emails)
		clock, _name, label = emails[0]
		self.assertEqual(label, "1 day(s)")
		self.assertTrue(
			starts - timedelta(days=1) <= clock < starts - timedelta(days=1) + timedelta(minutes=4)
		)
		self.assertEqual(self.errors, [])

	def test_an_all_day_events_reminder_goes_out_at_its_time_of_day(self):
		"""The TIME column reaches Python as a timedelta, which datetime.combine
		refused: every all-day "1 day before at 08:00" raised and was dropped."""
		self.make_event(
			self.day,
			[{"type": "Email", "before": 1, "interval": "days", "time": "08:00"}],
			all_day=1,
		)
		at = self.day - timedelta(days=1) + timedelta(hours=8)

		emails, _popups = self.sweep(at - timedelta(hours=1), self.day + timedelta(hours=1))

		self.assertEqual(self.errors, [])
		self.assertEqual(len(emails), 1, emails)
		self.assertTrue(at <= emails[0][0] < at + timedelta(minutes=4))

	def test_a_reminder_set_after_its_time_still_goes_out_once_before_the_event(self):
		"""What the in-progress branch was for: an event created five minutes
		before it starts with a "10 minutes before" reminder."""
		starts = self.day.replace(hour=10)
		self.make_event(starts, [{"type": "Notification", "before": 10, "interval": "minutes"}])

		_emails, popups = self.sweep(starts - timedelta(minutes=5), starts + timedelta(hours=1))

		self.assertEqual(len(popups), 1, popups)
		self.assertLess(popups[0][0], starts)

	def test_settings_default_reminders_fire_for_events_without_their_own(self):
		"""The defaults were built as plain dicts and read with attribute access:
		'dict' object has no attribute 'owner', logged on every sweep, sent never."""
		self.set_global_reminders(
			[{"type": "Notification", "before": 10, "interval": "minutes"}],
			[{"type": "Email", "before": 1, "interval": "days", "time": "09:00"}],
		)
		starts = self.day.replace(hour=10)
		timed = self.make_event(starts)
		all_day = self.make_event(self.day + timedelta(days=1), all_day=1)

		emails, popups = self.sweep(starts - timedelta(hours=2), starts + timedelta(hours=1))

		self.assertEqual(self.errors, [])
		self.assertEqual([name for _clock, name, _before in popups], [timed.name])
		self.assertTrue(starts - timedelta(minutes=10) <= popups[0][0] < starts - timedelta(minutes=6))
		# the all-day default, at 09:00 the day before (that is, the timed event's day)
		self.assertEqual([(name, label) for _clock, name, label in emails], [(all_day.name, "1 day(s)")])

	def test_settings_defaults_do_not_stack_on_an_events_own_reminders(self):
		"""Custom versus default is decided per event. Joined per interval, an
		event with only an hours reminder also got every minutes default."""
		self.set_global_reminders([{"type": "Notification", "before": 10, "interval": "minutes"}], [])
		starts = self.day.replace(hour=10)
		self.make_event(starts, [{"type": "Email", "before": 1, "interval": "hours"}])

		emails, popups = self.sweep(starts - timedelta(hours=2), starts + timedelta(hours=1))

		self.assertEqual(popups, [])
		self.assertEqual([label for _clock, _name, label in emails], ["1 hour(s)"])


class ReminderLedgerSurvivesClearCacheTest(IntegrationTestCase):
	"""The sent ledger is the only record that a reminder went out. ``frappe.clear_cache``
	deletes every site key no hook names, and ``rename_doc`` -- which the Acumatica
	sync runs on a renamed customer -- calls it, as do migrate and a Role save; and a
	cache redis that is bounded evicts, or restarts empty. So it is a table."""

	REMINDER = frappe._dict(
		event_name="EV-LEDGER-CLEAR-CACHE",
		notification_type="Email",
		trigger_datetime=datetime(2026, 3, 2, 9, 50),
	)

	def setUp(self):
		super().setUp()
		forget_sent_reminders()
		self.addCleanup(forget_sent_reminders)

	def test_the_cache_keeps_only_what_the_upgrade_carries_over(self):
		"""The legacy keys stay persistent for one release, so the clear_cache migrate
		runs before its patches cannot delete what the carry-over patches read."""
		from crm import hooks

		self.assertLessEqual(
			set(hooks.persistent_cache_keys),
			{"acumatica_token::*", "acumatica_inflight::*", "crm:event_reminder_sent:*"},
		)

	def test_claims_in_the_cache_are_carried_into_the_ledger_on_upgrade(self):
		"""A reminder claimed in redis just before the upgrade must not be sent again
		after it -- migrate's own clear_cache first, as SiteMigration.setUp runs it."""
		from crm.api.event import _claim_reminder
		from crm.patches.v1_0 import carry_event_reminder_claims_to_ledger as patch

		key = "crm:event_reminder_sent:EV-LEDGER-CARRY:Email:2026-03-02T09:50:00"
		frappe.cache.set(frappe.cache.make_key(key), 1, ex=600)
		self.addCleanup(frappe.cache.delete_value, key)
		frappe.clear_cache()

		patch.execute()
		patch.execute()  # idempotent

		carried = frappe._dict(self.REMINDER, event_name="EV-LEDGER-CARRY")
		self.assertFalse(_claim_reminder(carried), "the reminder would be mailed a second time")

	def test_a_claimed_reminder_stays_claimed_across_a_clear_cache(self):
		from crm.api.event import _claim_reminder

		self.assertTrue(_claim_reminder(self.REMINDER))

		frappe.clear_cache()
		# and every key the site has in the cache redis, as a flush or a restart would
		frappe.cache.delete_keys("")

		self.assertFalse(_claim_reminder(self.REMINDER), "the reminder would be mailed a second time")

	def test_a_claim_outlives_the_sweeps_own_rollback(self):
		"""The mail goes out before the job commits; a job that then fails must not
		forget it sent it."""
		from crm.api.event import _claim_reminder

		self.assertTrue(_claim_reminder(self.REMINDER))
		frappe.db.rollback()
		self.assertFalse(_claim_reminder(self.REMINDER))

	def test_two_sweeps_at_once_send_a_reminder_once(self):
		"""Each sweep in its own worker, with its own database connection, claiming the
		same reminder at the same moment: exactly one may send it."""
		import threading

		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier = threading.Barrier(2)
		claims, errors = [], []

		def sweep():
			frappe.init(site, sites_path=sites_path)
			frappe.connect()
			try:
				from crm.api.event import _claim_reminder

				barrier.wait(timeout=30)
				claims.append(_claim_reminder(self.REMINDER))
			except Exception as e:
				errors.append(e)
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=sweep) for _ in range(2)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(timeout=60)

		self.assertEqual(errors, [])
		self.assertEqual(sorted(claims), [False, True])

	def test_old_rows_are_purged_and_recent_ones_kept(self):
		from frappe.utils import add_days

		from crm.api.event import _claim_reminder
		from crm.fcrm.doctype.crm_event_reminder_sent.crm_event_reminder_sent import KEEP_DAYS, purge_old
		from crm.utils.autonomous import autonomous_db

		old = frappe._dict(self.REMINDER, event_name="EV-LEDGER-OLD")
		self.assertTrue(_claim_reminder(old))
		self.assertTrue(_claim_reminder(self.REMINDER))
		with autonomous_db() as db:
			db.sql(
				"update `tabCRM Event Reminder Sent` set sent_at = %s where event = %s",
				(add_days(now_datetime(), -KEEP_DAYS - 1), "EV-LEDGER-OLD"),
			)

		purge_old()

		self.assertTrue(_claim_reminder(old), "a purged row frees nothing that could still fire")
		self.assertFalse(_claim_reminder(self.REMINDER))
