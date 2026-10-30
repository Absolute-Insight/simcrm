"""
Event notification handling for CRM.

This module handles event notifications for the CRM system, supporting both:
1. Custom event notifications set on individual events
2. Global default notifications from CRM Settings for events without custom notifications

One sweep, on the scheduler's every-tick job, sends each reminder once: when its
trigger time has passed, before the event starts, and no earlier sweep has sent
it. A sweep that runs late (a busy worker, a restart) catches up, as does a
reminder added after its time had already passed.

Global notifications are configured in CRM Settings under the Calendar tab and are applied
to events that don't have custom notifications set. This ensures all events can receive
reminders even if users don't configure them individually.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, escape_html, format_datetime, get_time, now_datetime

# How late a reminder may still go out. It covers a delayed sweep and a reminder
# set after its time (a meeting booked five minutes before it starts), and it
# bounds what losing the sent ledger below can cost: at most the last hour's
# reminders are sent a second time.
REMINDER_CATCH_UP = timedelta(hours=1)
# Sent ledger, in the cache: one key per reminder per trigger time.
SENT_REMINDER_KEY = "crm:event_reminder_sent:"


def trigger_offset_event_notifications():
	"""Send every event reminder that has come due, once.

	The only reminder job. There used to be one per interval, each sending
	whatever fell within a window around the trigger time (+/-5 minutes up to
	+/-4 days) with no record of what had gone out: the every-tick job and the
	hourly one both swept hours, every tick inside a window sent again, and an
	event in progress widened the window to the whole meeting -- 17 emails for
	"10 minutes before", 48 for "1 hour before", to every external participant.
	The once-a-day "days" sweep, meanwhile, could not reach a +/-8 h window
	around a business-hours trigger, so those never fired.
	"""

	if frappe.flags.in_import or frappe.flags.in_patch:
		return

	current_time = now_datetime()
	for notification in _due_notifications(current_time):
		try:
			if not _claim_reminder(notification):
				continue

			if notification.notification_type == "Email":
				_send_email_notification(
					notification,
					notification.starts_on,
					notification.before_value,
					notification.notification_interval,
				)
			elif notification.notification_type == "Notification":
				_send_system_notification(notification)

		except Exception as e:
			frappe.log_error(
				f"Error processing {notification.notification_interval} notification for event {notification.event_name}: {e!s}"
			)
			continue


def _due_notifications(current_time):
	"""Every reminder whose trigger time has passed, within REMINDER_CATCH_UP,
	for an event that has not started yet.

	A site-wide sweep. This used to filter on `e.owner = frappe.session.user OR
	ep.email = frappe.session.user`, which under the scheduler is Administrator:
	every event a rep or manager created -- including the meetings and visits
	the planner writes -- was excluded, and no reminder ever fired for anyone
	but Administrator. Who each reminder reaches is decided per event by
	_notification_audience (owner plus participants), not by who runs the job.
	"""

	rows = frappe.db.sql(
		"""
		SELECT
			e.name as event_name,
			e.subject,
			e.starts_on,
			e.ends_on,
			e.owner,
			e.description,
			e.all_day as all_day_event,
			en.type as notification_type,
			en.before as before_value,
			en.time as time_of_day,
			en.interval as notification_interval
		FROM `tabEvent` e
		LEFT JOIN `tabEvent Notifications` en
			ON en.parent = e.name AND en.parenttype = 'Event' AND en.parentfield = 'notifications'
		WHERE e.starts_on > %(now)s
		AND e.status != 'Cancelled'
		ORDER BY e.starts_on, e.name, en.idx
	""",
		{"now": current_time},
		as_dict=True,
	)

	global_notifications = None
	due = []
	for row in rows:
		if row.notification_type:
			notifications = [row]
		else:
			# No reminder of its own, so the defaults from CRM Settings apply. Decided
			# per event: the join is not filtered by interval, so an event with only
			# an hours reminder does not pick up the minutes defaults as well.
			if global_notifications is None:
				global_notifications = _global_notifications()
			notifications = _apply_global_notifications(row, global_notifications)

		for notification in notifications:
			try:
				notification.trigger_datetime = _calculate_trigger_datetime(
					notification.starts_on,
					notification.before_value,
					notification.notification_interval,
					notification.all_day_event,
					notification.time_of_day,
				)
			except Exception as e:
				frappe.log_error(f"Error scheduling notification for event {notification.event_name}: {e!s}")
				continue

			if (
				notification.trigger_datetime
				<= current_time
				< (notification.trigger_datetime + REMINDER_CATCH_UP)
			):
				due.append(notification)

	if due:
		participants = {}
		for participant in frappe.get_all(
			"Event Participants",
			filters={
				"parenttype": "Event",
				"parent": ["in", list({n.event_name for n in due})],
			},
			fields=["parent", "email"],
			order_by="idx asc",
		):
			if participant.email:
				participants.setdefault(participant.parent, []).append(participant.email)
		for notification in due:
			notification.event_participants = participants.get(notification.event_name, [])

	return due


def _global_notifications():
	"""The default reminders from CRM Settings, as (table, row) pairs."""

	fcrm_settings = frappe.get_single("FCRM Settings")
	return [
		*(("regular", row) for row in fcrm_settings.get("event_notifications") or []),
		*(("all_day", row) for row in fcrm_settings.get("all_day_event_notifications") or []),
	]


def _apply_global_notifications(event, global_notifications):
	"""The CRM Settings defaults as this event's own reminders: the all-day table
	for an all-day event, the regular one otherwise.

	Built as frappe._dict: the senders read them by attribute, which on a plain
	dict raised "'dict' object has no attribute 'owner'" on every sweep and sent
	nothing.
	"""

	table = "all_day" if event.all_day_event else "regular"
	return [
		frappe._dict(
			event,
			notification_type=row.type,
			before_value=row.before,
			time_of_day=row.time,
			notification_interval=row.interval,
		)
		for table_type, row in global_notifications
		if table_type == table
	]


def _claim_reminder(notification) -> bool:
	"""Record in the sent ledger that this reminder is going out; False when an
	earlier sweep already sent it.

	Keyed by what the reminder is rather than by its row: the frontend re-saves
	an event's reminder rows under new names, and a moved event's reminder is a
	new one and should fire again. Two rows of the same type that land on the
	same minute are one reminder. SET NX makes the claim atomic, so two sweeps
	running at once cannot both send it.
	"""

	key = frappe.cache.make_key(
		f"{SENT_REMINDER_KEY}{notification.event_name}:{notification.notification_type}:"
		f"{notification.trigger_datetime.isoformat()}"
	)
	# kept past the end of the catch-up window, after which it cannot fire again
	expires = int(REMINDER_CATCH_UP.total_seconds()) + 600
	return bool(frappe.cache.set(key, 1, ex=expires, nx=True))


def _calculate_trigger_datetime(event_start, before_value, interval, all_day_event, time_of_day):
	"""
	Calculate when the notification should be triggered based on event start time and interval.

	Args:
		event_start (datetime): Event start datetime
		before_value (int): How many units before the event
		interval (str): The interval type ('minutes', 'hours', 'days', 'weeks')
		all_day_event (bool): Whether this is an all-day event
		time_of_day (time): Specific time to send notification for all-day events

	Returns:
		datetime: When the notification should be triggered
	"""

	if all_day_event and time_of_day and interval in ["days", "weeks"]:
		if interval == "days":
			trigger_date = event_start.date() - timedelta(days=before_value)
		elif interval == "weeks":
			trigger_date = event_start.date() - timedelta(weeks=before_value)

		# A Time column is read back from MariaDB as a timedelta, which
		# datetime.combine refuses: every all-day reminder with a time raised here.
		trigger_datetime = datetime.combine(trigger_date, get_time(time_of_day))
	else:
		interval_kwargs = _get_interval_kwargs(interval, before_value)
		trigger_datetime = add_to_date(event_start, **interval_kwargs)

	return trigger_datetime


def _get_interval_kwargs(interval, before_value):
	"""
	Get the appropriate keyword arguments for add_to_date based on interval type.

	Args:
		interval (str): The interval type ('minutes', 'hours', 'days', 'weeks')
		before_value (int): How many units before the event

	Returns:
		dict: Keyword arguments for add_to_date with negative values
	"""
	interval_mapping = {
		"minutes": {"minutes": -before_value},
		"hours": {"hours": -before_value},
		"days": {"days": -before_value},
		"weeks": {"weeks": -before_value},
	}

	return interval_mapping.get(interval, {"hours": -before_value})


def _notification_audience(notification) -> set[str]:
	"""Everyone a given event concerns: its owner and its participants.

	One definition, used by both channels, so the set of people an event
	reminder reaches cannot differ between the email and the in-app popup.
	"""
	audience = set()

	if notification.owner:
		audience.add(notification.owner)

	participant_emails = notification.get("event_participants") or []
	if participant_emails:
		audience.update(participant_emails)
	else:
		event_doc = frappe.get_doc("Event", notification.event_name)
		for participant in event_doc.get("event_participants", []):
			email = getattr(participant, "email", None)
			if email:
				audience.add(email)

	return {email for email in audience if email}


def _send_email_notification(notification, event_start, before_value, interval):
	"""Send email notification for an event"""

	try:
		# Plain text: the subject line is not HTML, so escaping it here would put
		# literal &amp; in front of the reader.
		subject = _("Event reminder: {0}").format(notification.subject)

		recipients = _notification_audience(notification)
		# Long-standing behaviour: the Administrator account is not emailed.
		recipients.discard("Administrator")
		recipients = sorted(recipients)

		if not recipients:
			return
		time_remaining_text = _format_time_remaining(before_value, interval)

		# Escaped here, not in the template: frappe's Jinja environment runs with
		# autoescape off, so `{{ subject }}` there would emit raw HTML exactly as
		# the f-string this replaced did. An event title is typed by a user and
		# this mail is delivered to external participants, so an unescaped field
		# is somebody else's inbox carrying markup we chose to send them.
		#
		# Rendered through sendmail's own `template`/`args` rather than a
		# render_template call, matching crm_invitation. Same output, and it
		# keeps this off the frappe-ssti rule, which flags every render_template
		# regardless of whether the template name is a literal.
		frappe.sendmail(
			recipients=recipients,
			subject=subject,
			template="event_reminder",
			args={
				"subject": escape_html(notification.subject or ""),
				"description": escape_html(notification.description or ""),
				# The reader's own format, rather than a bare SQL-shaped timestamp.
				"start_time": escape_html(format_datetime(event_start)),
				"time_remaining": escape_html(time_remaining_text),
				"brand": escape_html(frappe.db.get_single_value("FCRM Settings", "brand_name") or "Vectora"),
			},
			reference_doctype="Event",
			reference_name=notification.event_name,
			now=True,
		)

	except Exception as e:
		frappe.log_error(f"Failed to send email for event {notification.event_name}: {e!s}")


def _format_time_remaining(before_value, interval):
	"""
	Format the time remaining message based on the interval and before value.

	Args:
		before_value (int): The number of units before the event
		interval (str): The interval type ('minutes', 'hours', 'days', 'weeks')

	Returns:
		str: Formatted time remaining message
	"""
	interval_labels = {"minutes": "minute(s)", "hours": "hour(s)", "days": "day(s)", "weeks": "week(s)"}

	interval_label = interval_labels.get(interval, "unit(s)")
	return f"{before_value} {interval_label}"


def _send_system_notification(notification):
	"""Push the in-app reminder to the people the event concerns.

	`publish_realtime` with no room, user or doctype falls through to
	`get_site_room()` — frappe's own comment on that branch reads "This will be
	broadcasted to all Desk users". The payload carries the event's subject,
	description, owner and the participants' email addresses, so every logged-in
	rep was shown a popup for meetings they had nothing to do with, naming who
	was attending. Scoped to one user room per recipient instead.

	Unlike the email, the Administrator is not filtered out: if they own the
	event, the reminder is theirs to see.
	"""
	for user in sorted(_notification_audience(notification)):
		frappe.publish_realtime("event_notification", notification, user=user)
