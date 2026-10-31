# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""An image placed in an outgoing email reaches the recipient, and stays private.

The composer uploads it as a private File on the deal. The recipient's mail
client has no session, so the ``/private/files/`` URL frappe writes into the
mail is a 403 for them; uploading it public instead let every rep list and
download it (audit FE-95, and the review of its first fix). The mail carries
the image as a ``cid:`` part instead -- but only an image uploaded to the very
deal the email is about, that the sender may read, and that is not in quoted
reply content. The html is not always the sender's own: a reply quotes the
received mail, ``<img src>`` and all, so an outside sender could otherwise name
a deal's file and have the rep's reply mail it back to them.
"""

from __future__ import annotations

import email
import io
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from pypdf import PdfWriter

OWNER = "inline-image-owner@crmtest.test"
OTHER = "inline-image-other@crmtest.test"
# 1x1 transparent PNG.
PNG = bytes.fromhex(
	"89504e470d0a1a0a0000000d4948445200000001000000010806000000"
	"1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
# frappe points a File whose bytes it already holds at the existing file_url,
# so every other file a test makes needs bytes of its own.
OTHER_PNG = PNG + b"other deal"


def blank_pdf() -> bytes:
	# frappe parses an uploaded PDF, so it has to be a real one.
	writer = PdfWriter()
	writer.add_blank_page(width=72, height=72)
	buffer = io.BytesIO()
	writer.write(buffer)
	return buffer.getvalue()


def ensure_rep(address: str, name: str) -> None:
	if not frappe.db.exists("User", address):
		user = frappe.get_doc(
			{"doctype": "User", "email": address, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


def upload(file_name: str, content: bytes, deal: str) -> frappe.Document:
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"is_private": 1,
			"attached_to_doctype": "CRM Deal",
			"attached_to_name": deal,
			"content": content,
		}
	).insert(ignore_permissions=True)


def build(content: str, deal: str | None) -> email.message.Message:
	"""Queue a mail about ``deal`` as the current user and return what was queued."""
	reference = {"reference_doctype": "CRM Deal", "reference_name": deal} if deal else {}
	queued = frappe.sendmail(
		recipients=["buyer@customer.test"], subject="Pricing", content=content, **reference
	)
	return email.message_from_string(frappe.db.get_value("Email Queue", queued.name, "message"))


def html_of(message: email.message.Message) -> str:
	for part in message.walk():
		if part.get_content_type() == "text/html":
			return part.get_payload(decode=True).decode()
	raise AssertionError("no html part")


def inline_images(message: email.message.Message) -> list[email.message.Message]:
	return [part for part in message.walk() if part.get_content_maintype() == "image"]


class EmailInlineImageTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		# Outside developer mode frappe reads hooks.py from the site's shared
		# cache, which a local test site's workers refill from whatever checkout
		# they started on. Developer mode loads them in this process, from this
		# code, so the Email Queue doc_event is the one under test.
		self.enterContext(patch.dict(frappe.local.conf, {"developer_mode": 1}))
		frappe.set_user("Administrator")
		ensure_rep(OWNER, "Owner")
		ensure_rep(OTHER, "Other")
		self.deal = self.new_deal()
		self.file = self.attach("pricing.png", PNG, self.deal.name)

	def new_deal(self) -> frappe.Document:
		deal = frappe.get_doc({"doctype": "CRM Deal", "deal_owner": OWNER}).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True, ignore_permissions=True)
		return deal

	def attach(self, file_name: str, content: bytes, deal: str) -> frappe.Document:
		file = upload(file_name, content, deal)
		# Cleanups run last-in first-out, so a deal's files go before the deal.
		self.addCleanup(frappe.delete_doc, "File", file.name, force=True, ignore_permissions=True)
		return file

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_an_image_the_sender_can_read_is_sent_inline_and_stays_private(self):
		frappe.set_user(OWNER)
		self.assertTrue(self.file.is_downloadable())

		message = build(f'<p>See below</p><img src="{self.file.file_url}" alt="pricing">', self.deal.name)

		html = html_of(message)
		self.assertNotIn("/private/files/", html)
		[image] = inline_images(message)
		self.assertIn(f'src="cid:{image["Content-ID"].strip("<>")}"', html)
		self.assertEqual(image.get_payload(decode=True), PNG)
		self.assertEqual(image.get_content_type(), "image/png")
		# The html and its image travel together, as frappe's own embed= does.
		self.assertEqual(
			[p.get_content_type() for p in message.walk()][:4],
			["multipart/mixed", "multipart/alternative", "text/plain", "multipart/related"],
		)
		self.assertEqual(frappe.db.get_value("File", self.file.name, "is_private"), 1)

	def test_an_email_sent_from_the_deal_queues_the_image_inline(self):
		# The composer's own path: communication.email.make builds the queued
		# MIME in the rep's request, so the check runs as the rep.
		from frappe.core.doctype.communication.email import make

		frappe.set_user(OWNER)
		sent = make(
			doctype="CRM Deal",
			name=self.deal.name,
			recipients="buyer@customer.test",
			subject="Pricing",
			content=f'<p>See below</p><img src="{self.file.file_url}">',
			send_email=1,
		)

		frappe.set_user("Administrator")
		queued = frappe.get_all("Email Queue", filters={"communication": sent["name"]}, pluck="message")
		self.assertEqual(len(queued), 1)
		message = email.message_from_string(queued[0])
		self.assertNotIn("/private/files/", html_of(message))
		[image] = inline_images(message)
		self.assertEqual(image.get_payload(decode=True), PNG)
		# Rewriting the queued mail keeps the placeholders frappe fills per
		# recipient at send time.
		self.assertIn("<!--email_open_check-->", queued[0])
		self.assertIn("<!--unsubscribe_url-->", queued[0])
		# The timeline keeps the CRM's own link, which the rep's session can load.
		self.assertIn(self.file.file_url, frappe.db.get_value("Communication", sent["name"], "content"))

	def test_an_image_the_sender_cannot_read_is_not_pulled_into_the_email(self):
		frappe.set_user(OTHER)
		self.assertFalse(self.file.is_downloadable())

		message = build(f'<img src="{self.file.file_url}">', self.deal.name)

		self.assertEqual(inline_images(message), [])
		self.assertIn(f"{self.file.file_url}", html_of(message))

	def reply(self, content: str) -> email.message.Message:
		"""Reply on the deal as the current user, the way the composer sends it."""
		from frappe.core.doctype.communication.email import make

		sent = make(
			doctype="CRM Deal",
			name=self.deal.name,
			recipients="attacker@outside.test",
			subject="Re: Pricing",
			content=content,
			send_email=1,
		)
		user = frappe.session.user
		frappe.set_user("Administrator")
		[queued] = frappe.get_all("Email Queue", filters={"communication": sent["name"]}, pluck="message")
		frappe.set_user(user)
		return email.message_from_string(queued)

	def test_an_image_from_another_deal_is_not_mailed_out(self):
		# An outside sender writes <img src="/private/files/..."> naming a file
		# on some other deal; frappe keeps the src on the received mail. The rep
		# can read that deal, so a read check alone would inline its bytes and
		# send them to the attacker. Outside any quote here, so the deal check is
		# what stops it.
		other_deal = self.new_deal()
		elsewhere = self.attach("contract.png", OTHER_PNG, other_deal.name)
		frappe.set_user(OWNER)
		self.assertTrue(elsewhere.is_downloadable())

		message = self.reply(f'<p>Sure</p><p><img src="{elsewhere.file_url}"></p>')

		self.assertEqual(inline_images(message), [])
		self.assertIn(elsewhere.file_url, html_of(message))

	def test_a_quoted_image_from_the_deal_itself_is_not_mailed_back(self):
		# The composer quotes the received mail verbatim -- out of the rep's
		# sight -- when they click Reply. An image the attacker names there that
		# is on this very deal passes the deal and read checks, so the quote
		# itself must keep it out. A fresh image above the quote still goes.
		quoted = self.attach("site-survey.png", OTHER_PNG, self.deal.name)
		frappe.set_user(OWNER)
		self.assertTrue(quoted.is_downloadable())

		# What EmailArea.vue's reply() hands frappe: the rep's paragraphs, then
		# the received mail inside a blockquote.
		message = self.reply(
			f'<p>Thanks, see ours</p><p><img src="{self.file.file_url}"></p>'
			f'<blockquote><p>Can you resend this?</p><p><img src="{quoted.file_url}"></p></blockquote>'
		)

		# Only the fresh image went inline; the quoted one kept its link.
		self.assertEqual([p.get_payload(decode=True) for p in inline_images(message)], [PNG])
		self.assertIn(quoted.file_url, html_of(message))

	def test_a_quoted_image_that_closes_the_quote_early_is_not_mailed_back(self):
		# reply() builds `<blockquote>${received}</blockquote>` from a string,
		# so a received mail saying `</blockquote><img ...>` puts its image
		# after the quote rather than in it.
		quoted = self.attach("site-survey.png", OTHER_PNG, self.deal.name)
		frappe.set_user(OWNER)

		message = self.reply(
			f'<p>Thanks</p><blockquote><p>Hi</p></blockquote><p><img src="{quoted.file_url}"></p>'
		)

		self.assertEqual(inline_images(message), [])
		self.assertIn(quoted.file_url, html_of(message))

	def test_a_private_file_that_is_not_an_image_is_not_inlined(self):
		price_list = self.attach("Price List.pdf", blank_pdf(), self.deal.name)
		frappe.set_user(OWNER)
		self.assertTrue(price_list.is_downloadable())

		message = build(f'<img src="{price_list.file_url}">', self.deal.name)

		self.assertEqual([p for p in message.walk() if p.get_content_type() == "application/pdf"], [])
		# frappe quotes the URL as it expands it.
		self.assertIn("/private/files/Price%20List.pdf", html_of(message))
		self.assertNotIn("multipart/related", [p.get_content_type() for p in message.walk()])

	def test_an_email_about_no_document_inlines_nothing(self):
		frappe.set_user(OWNER)

		message = build(f'<img src="{self.file.file_url}">', None)

		self.assertEqual(inline_images(message), [])
		self.assertIn(self.file.file_url, html_of(message))

	def test_images_past_the_size_cap_keep_their_link(self):
		from crm.extends import email_inline_images

		second = self.attach("second.png", OTHER_PNG, self.deal.name)
		frappe.set_user(OWNER)
		self.enterContext(patch.object(email_inline_images, "MAX_INLINE_BYTES", len(PNG) + 4))

		message = build(f'<img src="{self.file.file_url}"><img src="{second.file_url}">', self.deal.name)

		[image] = inline_images(message)
		self.assertEqual(image.get_payload(decode=True), PNG)
		self.assertIn(second.file_url, html_of(message))

	def test_an_email_without_private_images_is_left_alone(self):
		frappe.set_user(OWNER)
		message = build('<p>Hi</p><img src="https://example.test/logo.png">', self.deal.name)

		self.assertEqual(inline_images(message), [])
		self.assertIn('src="https://example.test/logo.png"', html_of(message))
		self.assertNotIn("multipart/related", [p.get_content_type() for p in message.walk()])
