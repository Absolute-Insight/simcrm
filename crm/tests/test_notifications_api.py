# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The notification inbox costs a fixed number of queries, whatever its size.

``get_notifications`` runs on every app load and on every ``crm_notification``
event. It returned every notification the user had ever received, with one User
query per row for the sender's name, and the deal import leaves a rep with one
notification per imported deal. "Mark all as read" was a ``get_doc`` and a
``save`` per unread row, and each save published ``crm_notification``, which
every open tab answered by reloading that inbox.

A task assigned with no lead or deal behind it was labelled with the Lead route,
so the client asked vue-router for ``/leads/None`` and the row never rendered.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api import notifications as api

REP = "notifapi-rep@crmtest.test"
OTHER = "notifapi-other@crmtest.test"
SENDER = "notifapi-sender@crmtest.test"


def ensure_user(email: str, name: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


def make_notification(to_user: str, **values):
	return frappe.get_doc(
		{
			"doctype": "CRM Notification",
			"from_user": SENDER,
			"to_user": to_user,
			"type": "Assignment",
			"message": "Sender assigned a deal to you",
			"notification_text": "<div>assigned</div>",
			**values,
		}
	).insert(ignore_permissions=True, ignore_links=True)


@contextmanager
def count_sql():
	calls = []
	real_sql = frappe.db.sql

	def counting_sql(*args, **kwargs):
		calls.append(args[0] if args else kwargs.get("query"))
		return real_sql(*args, **kwargs)

	with patch.object(frappe.db, "sql", side_effect=counting_sql):
		yield calls


def realtime_events(publish) -> list:
	return [c for c in publish.call_args_list if c.args and c.args[0] == "crm_notification"]


class NotificationInboxTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(REP, "Rep")
		ensure_user(OTHER, "Other")
		ensure_user(SENDER, "Sender")
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def unread(self, user: str) -> int:
		return frappe.db.count("CRM Notification", {"to_user": user, "read": 0})

	def test_the_inbox_is_one_bounded_query(self):
		for _ in range(60):
			make_notification(REP)
		make_notification(OTHER)

		frappe.set_user(REP)
		with count_sql() as queries:
			rows = api.get_notifications()

		self.assertEqual(len(rows), 50)
		self.assertEqual(len(queries), 1, queries)
		self.assertEqual({row["to_user"] for row in rows}, {REP})
		self.assertEqual(rows[0]["from_user"], {"name": SENDER, "full_name": "Sender"})

	def test_the_inbox_is_newest_first(self):
		older = make_notification(REP, notification_text="<div>older</div>")
		newer = make_notification(REP, notification_text="<div>newer</div>")
		frappe.db.set_value("CRM Notification", older.name, "creation", "2026-01-01 09:00:00")

		frappe.set_user(REP)
		texts = [row["notification_text"] for row in api.get_notifications()]

		self.assertEqual(texts, [newer.notification_text, older.notification_text])

	def test_the_unread_count_covers_more_than_the_page(self):
		for _ in range(60):
			make_notification(REP)
		for _ in range(3):
			make_notification(REP, read=1)
		make_notification(OTHER)

		frappe.set_user(REP)
		self.assertEqual(api.get_unread_count(), 60)

	def test_mark_all_as_read_is_one_update_and_one_event(self):
		for _ in range(30):
			make_notification(REP)
		make_notification(OTHER)

		frappe.set_user(REP)
		with patch.object(frappe, "publish_realtime") as publish, count_sql() as queries:
			api.mark_as_read()

		self.assertEqual(self.unread(REP), 0)
		self.assertEqual(self.unread(OTHER), 1, "another user's notification was marked read")
		events = realtime_events(publish)
		self.assertEqual(len(events), 1, events)
		self.assertEqual(events[0].kwargs, {"user": REP, "after_commit": True})
		self.assertLessEqual(len(queries), 2, queries)

	def test_marking_one_document_leaves_the_rest_unread(self):
		# Any document that exists will do: mark_as_read matches on its name, and
		# the per-row save it used to make validated the link.
		make_notification(REP, notification_type_doctype="User", notification_type_doc=OTHER)
		make_notification(REP, notification_type_doctype="User", notification_type_doc=SENDER)
		make_notification(OTHER, notification_type_doctype="User", notification_type_doc=OTHER)

		frappe.set_user(REP)
		api.mark_as_read(doc=OTHER)

		read = frappe.get_all(
			"CRM Notification",
			filters={"to_user": ["in", [REP, OTHER]]},
			fields=["to_user", "notification_type_doc", "read"],
			order_by="to_user, notification_type_doc",
		)
		self.assertEqual(
			[(r.to_user, r.notification_type_doc, r.read) for r in read],
			[(OTHER, OTHER, 0), (REP, OTHER, 1), (REP, SENDER, 0)],
		)

	def test_nothing_to_mark_publishes_nothing(self):
		make_notification(REP, read=1)

		frappe.set_user(REP)
		with patch.object(frappe, "publish_realtime") as publish:
			api.mark_as_read()

		self.assertEqual(realtime_events(publish), [])

	def test_a_task_with_no_record_names_no_route(self):
		make_notification(
			REP,
			notification_type_doctype="CRM Task",
			notification_type_doc="TASK-STANDALONE",
		)
		make_notification(REP, reference_doctype="CRM Deal", reference_name="CRM-DEAL-NOTIFAPI")

		frappe.set_user(REP)
		rows = {row["notification_type_doc"] or row["reference_name"]: row for row in api.get_notifications()}

		self.assertIsNone(rows["TASK-STANDALONE"]["route_name"])
		self.assertEqual(rows["TASK-STANDALONE"]["hash"], "#tasks")
		self.assertEqual(rows["CRM-DEAL-NOTIFAPI"]["route_name"], "Deal")

	def test_a_new_notification_is_announced_after_commit(self):
		with patch.object(frappe, "publish_realtime") as publish:
			make_notification(REP)
			make_notification(REP)

		events = realtime_events(publish)
		self.assertEqual(len(events), 2)
		for event in events:
			self.assertEqual(event.kwargs, {"user": REP, "after_commit": True})
