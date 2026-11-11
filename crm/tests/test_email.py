import frappe
from frappe.core.doctype.communication.email import make
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_datetime, now_datetime

from crm.api.email import cancel_scheduled_email, send_scheduled_email_now, stamp_send_time


class TestCancelScheduledEmail(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Email Account", {"default_outgoing": 1}):
			frappe.get_doc(
				{
					"doctype": "Email Account",
					"email_account_name": "_Test Scheduled Send",
					"email_id": "scheduled-send@example.com",
					"enable_outgoing": 1,
					"default_outgoing": 1,
					"no_smtp_authentication": 1,
					"smtp_server": "localhost",
				}
			).insert(ignore_permissions=True)
		self.lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Scheduled", "email": "scheduled@example.com"}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def schedule(self):
		return make(
			doctype="CRM Lead",
			name=self.lead.name,
			subject="Following up",
			content="<p>Hi, following up on our call.</p>",
			recipients="scheduled@example.com",
			cc="cc@example.com",
			send_email=1,
			send_after=add_days(now_datetime(), 1),
		)["name"]

	def test_cancel_deletes_queue_and_returns_draft(self):
		name = self.schedule()
		self.assertEqual(frappe.db.get_value("Communication", name, "delivery_status"), "Scheduled")
		self.assertTrue(frappe.db.exists("Email Queue", {"communication": name}))

		draft = cancel_scheduled_email(name)

		self.assertFalse(frappe.db.exists("Communication", name))
		self.assertFalse(frappe.db.exists("Email Queue", {"communication": name}))
		self.assertEqual(draft["subject"], "Following up")
		self.assertEqual(draft["recipients"], "scheduled@example.com")
		self.assertEqual(draft["cc"], "cc@example.com")
		self.assertIn("following up on our call", draft["content"])

	def test_cancel_refuses_once_sending(self):
		name = self.schedule()
		frappe.db.set_value("Email Queue", {"communication": name}, "status", "Sending")

		with self.assertRaises(frappe.ValidationError):
			cancel_scheduled_email(name)
		self.assertTrue(frappe.db.exists("Communication", name))

	def test_cancel_refuses_unscheduled_email(self):
		name = self.schedule()
		frappe.db.set_value("Communication", name, "delivery_status", "Sent")

		with self.assertRaises(frappe.ValidationError):
			cancel_scheduled_email(name)

	def test_only_owner_can_cancel(self):
		name = self.schedule()
		frappe.db.set_value("Communication", name, "owner", "someone-else@example.com")

		with self.assertRaises(frappe.PermissionError):
			cancel_scheduled_email(name)
		self.assertTrue(frappe.db.exists("Communication", name))

	def test_owner_without_email_queue_access_can_cancel(self):
		name = self.schedule()
		queue = frappe.db.get_value("Email Queue", {"communication": name})
		self.assertTrue(frappe.db.exists("Email Queue Recipient", {"parent": queue}))
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "scheduled-send-owner@example.com",
				"first_name": "Owner",
				"send_welcome_email": 0,
				"roles": [{"role": "Sales User"}],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Communication", name, "owner", user.name)

		frappe.set_user(user.name)
		draft = cancel_scheduled_email(name)

		self.assertEqual(draft["subject"], "Following up")
		self.assertFalse(frappe.db.exists("Communication", name))
		self.assertFalse(frappe.db.exists("Email Queue", queue))
		self.assertFalse(frappe.db.exists("Email Queue Recipient", {"parent": queue}))

	def test_send_now_clears_schedule(self):
		name = self.schedule()

		send_scheduled_email_now(name)

		self.assertIsNone(frappe.db.get_value("Communication", name, "send_after"))
		self.assertNotEqual(frappe.db.get_value("Communication", name, "delivery_status"), "Scheduled")
		self.assertIsNone(frappe.db.get_value("Email Queue", {"communication": name}, "send_after"))

	def test_send_now_dates_email_by_send_time(self):
		name = self.schedule()
		frappe.db.set_value("Communication", name, "communication_date", "2026-01-01 10:00:00")

		send_scheduled_email_now(name)

		self.assertGreater(
			frappe.db.get_value("Communication", name, "communication_date"),
			get_datetime("2026-01-01 10:00:00"),
		)

	def test_scheduled_email_dated_when_sent(self):
		name = self.schedule()
		written = frappe.db.get_value("Communication", name, "communication_date")
		doc = frappe.get_doc("Communication", name)
		doc.delivery_status = "Sent"
		doc.send_after = add_days(written, -1)
		doc.communication_date = add_days(written, -2)

		stamp_send_time(doc)

		self.assertGreaterEqual(frappe.db.get_value("Communication", name, "communication_date"), written)

	def test_send_now_refuses_once_sending(self):
		name = self.schedule()
		frappe.db.set_value("Email Queue", {"communication": name}, "status", "Sending")

		with self.assertRaises(frappe.ValidationError):
			send_scheduled_email_now(name)

	# ---- the timeline (ours, not upstream's) ----

	def scheduled_activity(self):
		from crm.api.activities import get_activities

		activities = get_activities(self.lead.name)[0]
		return next(a for a in activities if a.get("activity_type") == "communication")

	def test_the_timeline_names_the_email_and_says_when_it_goes(self):
		"""The card acts on the email by name, and shows the time it will be sent."""
		name = self.schedule()

		activity = self.scheduled_activity()

		self.assertEqual(activity["name"], name)
		self.assertEqual(activity["data"]["delivery_status"], "Scheduled")
		self.assertEqual(
			get_datetime(activity["data"]["send_after"]),
			get_datetime(frappe.db.get_value("Communication", name, "send_after")),
		)
		self.assertTrue(activity["data"]["scheduled_by_me"])

	def test_a_colleague_sees_the_email_but_is_not_offered_its_actions(self):
		name = self.schedule()
		frappe.db.set_value("Communication", name, "owner", "someone-else@example.com")

		activity = self.scheduled_activity()

		self.assertFalse(activity["data"]["scheduled_by_me"])
		with self.assertRaises(frappe.PermissionError):
			cancel_scheduled_email(name)

	def test_an_email_that_went_out_carries_no_schedule(self):
		name = self.schedule()
		frappe.db.set_value("Communication", name, "delivery_status", "Sent")

		data = self.scheduled_activity()["data"]

		self.assertNotIn("send_after", data)
		self.assertNotIn("scheduled_by_me", data)

	# ---- send now (ours) ----

	def test_send_now_refuses_a_recipient_who_unsubscribed_since(self):
		"""frappe drops unsubscribed recipients when the email is queued and never
		looks again; sending now is a person choosing to mail them."""
		name = self.schedule()
		frappe.get_doc(
			{
				"doctype": "Email Unsubscribe",
				"email": "scheduled@example.com",
				"reference_doctype": "CRM Lead",
				"reference_name": self.lead.name,
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError) as refused:
			send_scheduled_email_now(name)

		self.assertIn("scheduled@example.com", str(refused.exception))
		self.assertEqual(frappe.db.get_value("Communication", name, "delivery_status"), "Scheduled")

	def test_send_now_does_not_claim_to_send_an_email_with_no_queue_left(self):
		"""frappe clears month-old queue rows whatever their status."""
		name = self.schedule()
		frappe.db.delete("Email Queue", {"communication": name})

		with self.assertRaises(frappe.ValidationError):
			send_scheduled_email_now(name)

		self.assertEqual(frappe.db.get_value("Communication", name, "delivery_status"), "Scheduled")
