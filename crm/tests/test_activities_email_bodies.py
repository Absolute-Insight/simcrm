# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The timeline carries emails' metadata and a snippet; bodies come on demand.

Every ``get_activities`` -- each page open, and each reload after a comment,
task or note -- used to ship up to 100 full html bodies: 3.6 MB for a deal of
120 Outlook-sized emails. Now a row carries a plain-text snippet, the newest
two (open by default) carry their body, and ``get_email_body`` serves the rest
to a reader the timeline would have shown them to.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.activities import (
	EXPANDED_EMAILS,
	SNIPPET_LENGTH,
	email_snippet,
	get_activities,
	get_email_body,
)

OWNER = "bodies-owner@crmtest.test"
OTHER = "bodies-other@crmtest.test"

# An Outlook-sized body, about 35 KB of html.
LINE = "<p style='color:#333333'>Line {i} of a long quoted Outlook thread &amp; its signature</p>"
BIG_BODY = "<div>" + "".join(LINE.format(i=i) for i in range(400)) + "</div>"


def ensure_rep(email: str, name: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


def add_email(doctype: str, name: str, subject: str, content: str = BIG_BODY, **extra) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": subject,
				"content": content,
				"sender": "buyer@customer.test",
				"recipients": "rep@crmtest.test",
				"reference_doctype": doctype,
				"reference_name": name,
				**extra,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def emails(activities: list[dict]) -> list[dict]:
	return [a for a in activities if a.get("activity_type") == "communication"]


class EmailSnippetTest(IntegrationTestCase):
	def test_tags_and_what_a_mail_client_hides_are_gone(self):
		html = (
			"<html><head><title>Hidden title</title><style>p { color: red }</style></head>"
			"<body><p>Hello</p><p>there</p><script>alert(1)</script><b>bold</b></body></html>"
		)
		self.assertEqual(email_snippet(html), "Hello there bold")

	def test_entities_are_decoded_and_whitespace_collapsed(self):
		html = "<p>Price&nbsp;&amp;\n\n terms &lt;b&gt; &#8211; ​now</p>"
		self.assertEqual(email_snippet(html), "Price & terms <b> – now")

	def test_no_markup_survives(self):
		snippet = email_snippet('<a href="x"><img src="y" onerror="z">Link</a><br/>after')
		self.assertEqual(snippet, "Link after")
		self.assertNotIn("onerror", snippet)

	def test_it_is_bounded(self):
		snippet = email_snippet(BIG_BODY)
		self.assertLessEqual(len(snippet), SNIPPET_LENGTH)
		self.assertTrue(snippet.endswith("…"))
		self.assertTrue(snippet.startswith("Line 0 of a long quoted Outlook thread & its signature Line 1"))

	def test_empty_and_plain_text(self):
		self.assertEqual(email_snippet(None), "")
		self.assertEqual(email_snippet(""), "")
		self.assertEqual(email_snippet("just  text"), "just text")

	def test_preheader_padding_does_not_use_up_the_read(self):
		padding = "&#847;&zwnj;&nbsp;" * 400
		html = f'<div style="display:none">{padding}</div><p>Your quote is ready</p>'
		self.assertEqual(email_snippet(html), "Your quote is ready")

	def test_indentation_does_not_use_up_the_read(self):
		cell = "\n" + " " * 40 + "<td>\n" + " " * 44 + "</td>"
		html = "<table>" + "<tr>" + cell * 60 + "</tr><tr><td>Delivery on Friday</td></tr></table>"
		self.assertEqual(email_snippet(html), "Delivery on Friday")

	def test_an_unclosed_head_ends_at_the_body(self):
		self.assertEqual(email_snippet("<html><head><meta charset=utf-8><body><p>Hello"), "Hello")
		self.assertEqual(email_snippet("<html><head><meta charset=utf-8><p>Hello"), "Hello")
		self.assertEqual(email_snippet("<head><style>p{}</style><title>T</title></head>Hi"), "Hi")

	def test_inline_tags_do_not_split_words_and_blocks_do(self):
		self.assertEqual(email_snippet("<p>Than<span>ks</span> a <b>lot</b></p>"), "Thanks a lot")
		self.assertEqual(email_snippet("Than</span>ks"), "Thanks")
		self.assertEqual(
			email_snippet("<p>one</p><p>two</p>three<br>four<div>five</div>"), "one two three four five"
		)
		self.assertEqual(email_snippet("<table><tr><td>a</td><td>b</td></tr></table>"), "a b")


class TimelinePayloadTest(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.deal = frappe.get_doc({"doctype": "CRM Deal"}).insert(ignore_permissions=True).name

	def tearDown(self):
		frappe.db.rollback()

	def test_only_the_newest_emails_carry_a_body(self):
		names = [add_email("CRM Deal", self.deal, f"Quote {i}") for i in range(5)]
		# pin "newest" rather than trust insert order; the timeline sorts on both
		for i, name in enumerate(names):
			when = f"2026-01-0{i + 1} 10:00:00"
			frappe.db.set_value(
				"Communication", name, {"creation": when, "communication_date": when}, update_modified=False
			)

		rows = {a["data"]["subject"]: a for a in emails(get_activities(self.deal)[0])}

		self.assertEqual(len(rows), 5)
		with_body = sorted(subject for subject, a in rows.items() if "content" in a["data"])
		self.assertEqual(with_body, ["Quote 3", "Quote 4"])
		self.assertEqual(EXPANDED_EMAILS, 2)
		for subject, row in rows.items():
			with self.subTest(subject=subject):
				self.assertTrue(row["data"]["snippet"].startswith("Line 0 of a long"))
				self.assertNotIn("<", row["data"]["snippet"])
				# what the collapsed row and its actions read is all there
				for key in ("sender", "recipients", "subject", "attachments", "sent_or_received"):
					self.assertIn(key, row["data"])

	def test_a_long_thread_is_tens_of_kilobytes_not_megabytes(self):
		for i in range(30):
			add_email("CRM Deal", self.deal, f"Thread {i}")

		payload = len(frappe.as_json(get_activities(self.deal), indent=None))

		# was 30 x 35 KB = over 1 MB; now two bodies and a short row per email
		self.assertGreater(len(BIG_BODY), 30_000)
		self.assertLess(payload, EXPANDED_EMAILS * len(BIG_BODY) + 30 * 1_000)

	def test_inline_bodies_are_sanitised(self):
		name = add_email("CRM Deal", self.deal, "Hostile", content="<p>Hi</p>")
		# straight to the column: the server must not lean on save-time cleaning
		frappe.db.set_value(
			"Communication",
			name,
			"content",
			'<p>Hi</p><script>alert(1)</script><img src="x.png" onerror="alert(2)">',
		)

		row = emails(get_activities(self.deal)[0])[0]

		self.assertIn("<p>Hi</p>", row["data"]["content"])
		self.assertNotIn("<script", row["data"]["content"])
		self.assertNotIn("onerror", row["data"]["content"])


class EmailBodyEndpointTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_rep(OWNER, "Owner")
		ensure_rep(OTHER, "Other")
		self.deal = (
			frappe.get_doc({"doctype": "CRM Deal", "deal_owner": OTHER}).insert(ignore_permissions=True).name
		)
		self.email = add_email("CRM Deal", self.deal, "Private quote", content="<p>Net price 41,000</p>")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def refusal(self, name: str) -> tuple[type, str]:
		frappe.local.message_log = []
		with self.assertRaises(frappe.DoesNotExistError) as raised:
			get_email_body(name)
		return type(raised.exception), str(raised.exception)

	def test_the_deals_reader_gets_the_body(self):
		frappe.set_user(OTHER)
		body = get_email_body(self.email)
		self.assertEqual(body["name"], self.email)
		self.assertIn("Net price 41,000", body["content"])

	def test_another_reps_deal_is_refused_like_a_missing_email(self):
		frappe.set_user(OWNER)
		self.assertFalse(frappe.has_permission("CRM Deal", "read", self.deal), "control")

		hidden = self.refusal(self.email)
		missing = self.refusal("no-such-email")

		self.assertEqual(hidden, missing, "no existence oracle")

	def test_an_assignee_through_todo_may_read_it(self):
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"reference_type": "CRM Deal",
				"reference_name": self.deal,
				"allocated_to": OWNER,
				"description": "Help with this deal",
			}
		).insert(ignore_permissions=True)
		frappe.set_user(OWNER)
		self.assertIn("Net price 41,000", get_email_body(self.email)["content"])

	def test_a_timeline_link_to_a_readable_deal_is_not_enough_if_the_reference_is_hidden(self):
		own_deal = (
			frappe.get_doc({"doctype": "CRM Deal", "deal_owner": OWNER}).insert(ignore_permissions=True).name
		)
		communication = frappe.get_doc("Communication", self.email)
		communication.add_link("CRM Deal", own_deal)
		communication.save(ignore_permissions=True)
		frappe.set_user(OWNER)
		self.assertTrue(frappe.has_permission("CRM Deal", "read", own_deal), "control")

		self.refusal(self.email)

	def test_only_kinds_the_timeline_shows(self):
		frappe.db.set_value("Communication", self.email, "communication_type", "Feedback")
		frappe.set_user(OTHER)
		self.refusal(self.email)

	def test_the_body_is_sanitised(self):
		frappe.db.set_value(
			"Communication",
			self.email,
			"content",
			'<p>Hi</p><script>alert(1)</script><a href="javascript:alert(2)">x</a>',
		)
		frappe.set_user(OTHER)
		content = get_email_body(self.email)["content"]
		self.assertIn("<p>Hi</p>", content)
		self.assertNotIn("<script", content)
		self.assertNotIn("javascript:", content)

	def test_plain_text_is_escaped_not_trusted(self):
		frappe.db.set_value("Communication", self.email, "content", "a < b & c")
		frappe.set_user(OTHER)
		self.assertEqual(get_email_body(self.email)["content"], "a &lt; b &amp; c")

	def test_a_variant_of_the_name_answers_for_the_same_row_and_rule(self):
		variants = [self.email.upper(), self.email + " "]
		frappe.set_user(OWNER)
		for variant in variants:
			with self.subTest(variant=variant):
				self.assertEqual(self.refusal(variant), self.refusal("no-such-email"))
		frappe.set_user(OTHER)
		for variant in variants:
			with self.subTest(variant=variant):
				self.assertEqual(get_email_body(variant)["name"], self.email)


class HiddenTimelineEmailTest(IntegrationTestCase):
	"""An email linked to the rep's deal but referenced to a record they cannot read.

	The timeline lists it -- frappe's docinfo follows timeline links -- but
	frappe's own rule for the Communication says no, so the row says who wrote
	to whom and when, and nothing of what: no snippet, no body, no files.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_rep(OWNER, "Owner")
		self.deal = (
			frappe.get_doc({"doctype": "CRM Deal", "deal_owner": OWNER}).insert(ignore_permissions=True).name
		)
		ensure_rep(OTHER, "Other")
		# a buyer at another rep's customer: the contact is hidden with it
		org = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": f"Hidden Org {frappe.generate_hash(length=6)}",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", org.name, "account_owner", OTHER)
		self.contact = (
			frappe.get_doc(
				{"doctype": "Contact", "first_name": "Hidden", "last_name": "Buyer", "company_name": org.name}
			)
			.insert(ignore_permissions=True)
			.name
		)
		older = [
			add_email("CRM Deal", self.deal, f"Readable {i}", content=f"<p>Readable body {i}</p>")
			for i in range(3)
		]
		self.hidden = add_email(
			"Contact", self.contact, "Hidden subject", content="<p>Secret terms</p>", recipients=OTHER
		)
		communication = frappe.get_doc("Communication", self.hidden)
		communication.cc = "copied@example.com"
		communication.bcc = "blind@example.com"
		communication.add_link("CRM Deal", self.deal)
		communication.save(ignore_permissions=True)
		for i, name in enumerate([*older, self.hidden]):
			when = f"2026-01-0{i + 1} 10:00:00"
			frappe.db.set_value(
				"Communication", name, {"creation": when, "communication_date": when}, update_modified=False
			)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def rows(self, activities: list[dict]) -> dict[str, dict]:
		return {
			("Hidden" if a["name"] == self.hidden else a["data"]["subject"]): a["data"]
			for a in emails(activities)
		}

	def test_the_row_carries_no_content_and_takes_no_open_slot(self):
		frappe.set_user(OWNER)
		self.assertFalse(frappe.has_permission("Contact", "read", self.contact), "control")

		rows = self.rows(get_activities(self.deal)[0])

		hidden = rows["Hidden"]
		self.assertTrue(hidden["hidden"])
		self.assertNotIn("snippet", hidden)
		self.assertNotIn("content", hidden)
		self.assertEqual(hidden["attachments"], [])
		self.assertNotIn("cc", hidden)
		self.assertNotIn("bcc", hidden)
		self.assertNotIn("blind@example.com", frappe.as_json(rows))
		self.assertNotIn("Secret", frappe.as_json(rows))
		# the newest two the rep may open are the ones that come open
		self.assertEqual(sorted(s for s, d in rows.items() if "content" in d), ["Readable 1", "Readable 2"])
		self.assertEqual(rows["Readable 0"]["snippet"], "Readable body 0")

	def test_the_row_says_only_who_on_our_side_and_when(self):
		frappe.set_user(OWNER)
		activity = next(a for a in emails(get_activities(self.deal)[0]) if a["name"] == self.hidden)
		data = activity["data"]

		for field in (
			"subject",
			"sender",
			"sender_full_name",
			"recipients",
			"cc",
			"bcc",
			"snippet",
			"content",
		):
			self.assertNotIn(field, data)
		payload = frappe.as_json(activity)
		for leak in ("Hidden subject", "buyer@customer.test", "copied@example.com", "blind@example.com"):
			self.assertNotIn(leak, payload)
		self.assertEqual(data["sent_or_received"], "Received")
		self.assertTrue(activity["communication_date"])
		# addressed to a CRM rep: the rep is named, by full name only
		self.assertEqual(data["internal_party"], "Other")
		self.assertEqual(data["internal_party_user"], OTHER)

	def test_outbound_names_the_rep_who_sent_it(self):
		frappe.db.set_value(
			"Communication",
			self.hidden,
			{"sent_or_received": "Sent", "sender": f"Other <{OTHER}>", "recipients": "buyer@customer.test"},
		)
		frappe.set_user(OWNER)
		data = self.rows(get_activities(self.deal)[0])["Hidden"]
		self.assertEqual(data["sent_or_received"], "Sent")
		self.assertEqual(data["internal_party"], "Other")
		self.assertNotIn("buyer@customer.test", frappe.as_json(data))

	def test_no_crm_user_on_it_is_a_colleague(self):
		frappe.db.set_value(
			"Communication",
			self.hidden,
			{"recipients": "sales@shared-mailbox.test, outsider@elsewhere.test", "cc": ""},
		)
		# an account without a CRM role is not named either
		if not frappe.db.exists("User", "outsider@elsewhere.test"):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "outsider@elsewhere.test",
					"first_name": "Outsider",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		frappe.set_user(OWNER)
		data = self.rows(get_activities(self.deal)[0])["Hidden"]
		self.assertEqual(data["internal_party"], "A colleague")
		self.assertIsNone(data["internal_party_user"])
		self.assertNotIn("Outsider", frappe.as_json(data))

	def test_the_lead_timeline_hides_it_the_same_way(self):
		lead = (
			frappe.get_doc({"doctype": "CRM Lead", "first_name": "Hidden lead", "lead_owner": OWNER})
			.insert(ignore_permissions=True)
			.name
		)
		communication = frappe.get_doc("Communication", self.hidden)
		communication.add_link("CRM Lead", lead)
		communication.save(ignore_permissions=True)
		frappe.set_user(OWNER)
		self.assertTrue(frappe.has_permission("CRM Lead", "read", lead), "control")

		activity = next(a for a in emails(get_activities(lead)[0]) if a["name"] == self.hidden)
		self.assertTrue(activity["data"]["hidden"])
		self.assertEqual(activity["data"]["internal_party"], "Other")
		self.assertNotIn("Hidden subject", frappe.as_json(activity))
		self.assertNotIn("buyer@customer.test", frappe.as_json(activity))

	def test_the_admin_sees_it_like_any_other(self):
		rows = {a["data"]["subject"]: a["data"] for a in emails(get_activities(self.deal)[0])}
		self.assertNotIn("hidden", rows["Hidden subject"])
		self.assertIn("Secret terms", rows["Hidden subject"]["content"])
		self.assertEqual(rows["Hidden subject"]["cc"], "copied@example.com")

	def test_a_reader_of_the_contact_sees_it_whole(self):
		# the contact's owner, given the deal through an assignment, reads it all
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"reference_type": "CRM Deal",
				"reference_name": self.deal,
				"allocated_to": OTHER,
				"description": "Help with this deal",
			}
		).insert(ignore_permissions=True)
		frappe.set_user(OTHER)
		self.assertTrue(frappe.has_permission("Contact", "read", self.contact), "control")
		data = next(a for a in emails(get_activities(self.deal)[0]) if a["name"] == self.hidden)["data"]
		self.assertNotIn("hidden", data)
		self.assertEqual(data["subject"], "Hidden subject")
		self.assertEqual(data["sender"], "buyer@customer.test")
