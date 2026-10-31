# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""An image placed in an outgoing email reaches the recipient, and stays private.

The composer uploads it as a private File on the deal. The recipient's mail
client has no session, so the ``/private/files/`` URL frappe writes into the
mail is a 403 for them; uploading it public instead let every rep list and
download it (audit FE-95, and the review of its first fix). The mail carries
the image as a ``cid:`` part instead -- but only one the sender may read, so a
hand-written ``src`` cannot pull another deal's file out through an email.
"""

from __future__ import annotations

import email
from unittest.mock import patch

import frappe
from frappe.email.email_body import get_email
from frappe.tests import IntegrationTestCase

OWNER = "inline-image-owner@crmtest.test"
OTHER = "inline-image-other@crmtest.test"
# 1x1 transparent PNG.
PNG = bytes.fromhex(
	"89504e470d0a1a0a0000000d4948445200000001000000010806000000"
	"1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def ensure_rep(address: str, name: str) -> None:
	if not frappe.db.exists("User", address):
		user = frappe.get_doc(
			{"doctype": "User", "email": address, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


def build(content: str) -> email.message.Message:
	mail = get_email(recipients=["buyer@customer.test"], subject="Pricing", content=content)
	return email.message_from_string(mail.as_string())


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
		# code, so make_email_body_message is the one under test.
		self.enterContext(patch.dict(frappe.local.conf, {"developer_mode": 1}))
		frappe.set_user("Administrator")
		ensure_rep(OWNER, "Owner")
		ensure_rep(OTHER, "Other")
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "deal_owner": OWNER}).insert(
			ignore_permissions=True
		)
		self.file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "pricing.png",
				"is_private": 1,
				"attached_to_doctype": "CRM Deal",
				"attached_to_name": self.deal.name,
				"content": PNG,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("File", self.file.name, force=True, ignore_permissions=True)
		frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)
		super().tearDown()

	def test_an_image_the_sender_can_read_is_sent_inline_and_stays_private(self):
		frappe.set_user(OWNER)
		self.assertTrue(self.file.is_downloadable())

		message = build(f'<p>See below</p><img src="{self.file.file_url}" alt="pricing">')

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
		# The timeline keeps the CRM's own link, which the rep's session can load.
		self.assertIn(self.file.file_url, frappe.db.get_value("Communication", sent["name"], "content"))

	def test_an_image_the_sender_cannot_read_is_not_pulled_into_the_email(self):
		frappe.set_user(OTHER)
		self.assertFalse(self.file.is_downloadable())

		message = build(f'<img src="{self.file.file_url}">')

		self.assertEqual(inline_images(message), [])
		self.assertIn(f"{self.file.file_url}", html_of(message))

	def test_an_email_without_private_images_is_left_alone(self):
		frappe.set_user(OWNER)
		message = build('<p>Hi</p><img src="https://example.test/logo.png">')

		self.assertEqual(inline_images(message), [])
		self.assertIn('src="https://example.test/logo.png"', html_of(message))
		self.assertNotIn("multipart/related", [p.get_content_type() for p in message.walk()])
