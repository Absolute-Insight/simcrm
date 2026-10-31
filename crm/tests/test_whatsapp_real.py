"""Against the real frappe_whatsapp, with only Meta stubbed.

Skipped where the app is not installed, which is every dev site but
whatsapp.localhost. CI's server lane installs it, so this is what proves a
bump of scripts/frappe-whatsapp-pin.env.
"""

import hashlib
import hmac
import json
from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase
from frappe.utils import get_fullname
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from crm.api.whatsapp import (
	can_send_whatsapp,
	create_whatsapp_message,
	get_whatsapp_messages,
	is_whatsapp_enabled,
	react_on_whatsapp_message,
)
from crm.integrations.whatsapp import webhook as guard
from crm.integrations.whatsapp.lines import get_sending_account

SECRET = "app-secret-a"
PHONE_A = "1000000001"
PHONE_B = "1000000002"
WABA = "2000000001"
SENDER = "27825550148"


def signed(body: bytes, secret: str = SECRET) -> str:
	return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def inbound(number=SENDER, phone_id=PHONE_A, text="Hello", message_id=None, name="Thandi", **message):
	return {
		"object": "whatsapp_business_account",
		"entry": [
			{
				"id": WABA,
				"changes": [
					{
						"field": "messages",
						"value": {
							"messaging_product": "whatsapp",
							"metadata": {"display_phone_number": "27110000000", "phone_number_id": phone_id},
							"contacts": [{"profile": {"name": name}, "wa_id": number}],
							"messages": [
								{
									"from": number,
									"id": message_id or f"wamid.{frappe.generate_hash(length=12)}",
									"timestamp": "1790000000",
									"type": "text",
									"text": {"body": text},
									**message,
								}
							],
						},
					}
				],
			}
		],
	}


def status(message_id, value="delivered", phone_id=PHONE_A):
	payload = inbound(phone_id=phone_id)
	change = payload["entry"][0]["changes"][0]
	change["value"].pop("messages")
	change["value"].pop("contacts")
	change["value"]["statuses"] = [{"id": message_id, "status": value, "recipient_id": SENDER}]
	return payload


def guards_overrides():
	return [
		method
		for method in frappe.get_hooks("override_whitelisted_methods")
		if method.startswith("frappe_whatsapp.") and "webhook" not in method and "flow_endpoint" not in method
	]


class WhatsAppCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if "frappe_whatsapp" not in frappe.get_installed_apps():
			raise __import__("unittest").SkipTest("frappe_whatsapp is not installed")

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("System Settings", "country", "South Africa")
		self.reps = [self.make_rep("wa-rep-a@example.com"), self.make_rep("wa-rep-b@example.com")]
		self.make_line("Line A", PHONE_A, self.reps[0])
		self.make_line("Line B", PHONE_B, self.reps[1], secret="app-secret-b")
		patcher = patch.object(guard, "_new_snapshot")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.flags.pop, "whatsapp_webhook_verified", None)
		self.logs_before = self.webhook_logs()

	def make_rep(self, email):
		if not frappe.db.exists("User", email):
			user = frappe.new_doc("User")
			user.update({"email": email, "first_name": email.split("@")[0], "send_welcome_email": 0})
			user.append_roles("Sales User")
			user.insert(ignore_permissions=True)
		return email

	def make_line(self, account, phone_id, user, secret=SECRET):
		doc = frappe.new_doc("WhatsApp Account")
		doc.update(
			{
				"account_name": account,
				"phone_id": phone_id,
				"business_id": WABA,
				"token": "token-" + phone_id,
				"url": "https://graph.invalid",
				"version": "v23.0",
				"webhook_verify_token": "verify-" + phone_id,
				"status": "Active",
			}
		)
		doc.insert(ignore_permissions=True)
		line = frappe.new_doc("CRM WhatsApp Line")
		line.update({"whatsapp_account": account, "user": user, "app_secret": secret})
		line.insert(ignore_permissions=True)

	def post(self, payload, signature="sign", secret=SECRET):
		body = json.dumps(payload).encode()
		headers = (
			{}
			if signature is None
			else {"X-Hub-Signature-256": signed(body, secret) if signature == "sign" else signature}
		)
		frappe.local.request = Request(
			EnvironBuilder(
				method="POST", data=body, content_type="application/json", headers=headers
			).get_environ()
		)
		frappe.local.form_dict = frappe._dict(payload)
		frappe.flags.whatsapp_webhook_verified = False
		return guard.webhook()

	def rows(self, **filters):
		"""This test's messages: a site may hold other rows, this suite must not read them."""
		filters["whatsapp_account"] = ("in", ("Line A", "Line B"))
		return frappe.get_all("WhatsApp Message", filters=filters, fields=["*"])

	def webhook_logs(self):
		return frappe.db.count("WhatsApp Notification Log", {"template": "Webhook"})


class TestSignature(WhatsAppCase):
	def assert_refused(self, response):
		self.assertEqual(response.status_code, 403)
		self.assertEqual(self.webhook_logs(), self.logs_before)
		self.assertFalse(self.rows(type="Incoming"))

	def test_no_signature_is_refused_with_no_row(self):
		self.assert_refused(self.post(inbound(), signature=None))

	def test_a_wrong_signature_is_refused_with_no_row(self):
		self.assert_refused(self.post(inbound(), signature="sha256=" + "0" * 64))

	def test_a_malformed_signature_is_refused(self):
		self.assert_refused(self.post(inbound(), signature="not-hmac-é"))

	def test_another_lines_secret_does_not_sign_for_this_line(self):
		self.assert_refused(self.post(inbound(), secret="app-secret-b"))

	def test_no_secret_configured_fails_closed(self):
		frappe.db.delete("__Auth", {"doctype": "CRM WhatsApp Line", "name": "Line A"})
		self.assert_refused(self.post(inbound()))

	def test_a_number_with_no_line_is_refused(self):
		self.assert_refused(self.post(inbound(phone_id="999")))

	def test_one_forged_change_among_good_ones_refuses_the_lot(self):
		payload = inbound()
		payload["entry"].append(inbound(phone_id=PHONE_B)["entry"][0])
		self.assert_refused(self.post(payload))

	def test_a_good_signature_is_accepted(self):
		self.assertEqual(self.post(inbound()).status_code, 200)
		self.assertEqual(len(self.rows(type="Incoming")), 1)

	def test_the_verify_handshake_passes_through(self):
		frappe.local.request = Request(EnvironBuilder(method="GET").get_environ())
		frappe.local.form_dict = frappe._dict(
			{"hub.verify_token": "verify-" + PHONE_A, "hub.challenge": "42"}
		)
		response = guard.webhook()
		self.assertEqual((response.status_code, response.get_data()), (200, b"42"))

	def test_the_unguarded_function_cannot_be_reached_around_the_override(self):
		"""frappe.handler.upload_file calls get_attr(method) with no override."""
		from frappe_whatsapp.utils import webhook as upstream

		frappe.local.request = Request(EnvironBuilder(method="POST", json=inbound()).get_environ())
		frappe.local.form_dict = frappe._dict(inbound())
		frappe.flags.whatsapp_webhook_verified = False
		with self.assertRaises(frappe.PermissionError):
			upstream.webhook()
		self.assertFalse(self.rows(type="Incoming"))

	def test_the_override_is_registered(self):
		self.assertEqual(
			frappe.override_whitelisted_method("frappe_whatsapp.utils.webhook.webhook"),
			"crm.integrations.whatsapp.webhook.webhook",
		)

	def test_a_list_in_place_of_an_id_is_denied_and_not_a_crash(self):
		payload = inbound(phone_id=["1", "2"])
		self.assertEqual(self.post(payload, signature="sha256=x").status_code, 403)
		payload = inbound()
		payload["entry"][0]["id"] = ["1"]
		payload["entry"][0]["changes"][0]["value"].pop("metadata")
		self.assertEqual(self.post(payload, signature="sha256=x").status_code, 403)

	def test_a_verify_token_must_be_a_string(self):
		frappe.local.request = Request(EnvironBuilder(method="GET").get_environ())
		frappe.local.form_dict = frappe._dict({"hub.verify_token": ["like", "v%"], "hub.challenge": "42"})
		self.assertEqual(guard.webhook().status_code, 403)

	def test_a_flow_reply_is_a_note_not_a_stored_flow(self):
		self.post(
			inbound(
				type="interactive", interactive={"type": "nfm_reply", "nfm_reply": {"response_json": "{}"}}
			)
		)
		self.assertEqual(self.rows(type="Incoming")[0].content_type, "text")

	def test_an_upstream_method_through_upload_file_is_refused(self):
		from crm.integrations.whatsapp.guards import refuse_upstream_methods_via_upload

		frappe.local.request = Request(
			EnvironBuilder(method="POST", path="/api/method/frappe.handler.upload_file").get_environ()
		)
		frappe.local.form_dict = frappe._dict(method="frappe_whatsapp.utils.bulk_messaging.retry_failed")
		with self.assertRaises(frappe.PermissionError):
			refuse_upstream_methods_via_upload()
		frappe.local.form_dict = frappe._dict(method="crm.api.something")
		refuse_upstream_methods_via_upload()

	def test_upstreams_open_functions_are_for_system_managers(self):
		for method in guards_overrides():
			self.assertTrue(
				frappe.override_whitelisted_method(method).startswith("crm.integrations.whatsapp.guards.")
			)
		from crm.integrations.whatsapp import guards

		frappe.set_user(self.reps[0])
		with self.assertRaises(frappe.PermissionError):
			guards.retry_failed("x")


class FakeResponse:
	def __init__(self, status=200, payload=None, content=b"data"):
		self.status_code, self._payload, self.content = status, payload, content

	def __enter__(self):
		return self

	def __exit__(self, *args):
		return False

	def json(self):
		return self._payload

	def raise_for_status(self):
		if self.status_code >= 400:
			raise requests.HTTPError(str(self.status_code))

	def iter_content(self, chunk_size=None):
		yield self.content


PNG = bytes.fromhex(
	"89504e470d0a1a0a0000000d4948445200000001000000010806000000"
	"1f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082"
)


def media(kind="image", message_id="wamid.media", mime="image/png", content=PNG, **extra):
	message = {"id": message_id, "from": SENDER, "type": kind, kind: {"id": "m1", **extra}}
	responses = [
		FakeResponse(payload={"url": "https://media.invalid/x", "mime_type": mime}),
		FakeResponse(content=content),
	]
	return message, responses


class TestMedia(WhatsAppCase):
	def store(self, message, responses):
		with patch.object(guard.requests, "get", side_effect=responses) as get:
			guard.store_media("Line A", message)
		frappe.set_user("Administrator")
		return get

	def stored(self, message_id="wamid.media"):
		return self.rows(message_id=message_id)[0]

	def test_media_is_private_from_the_start(self):
		self.post(inbound(text="first"))
		message, responses = media()
		get = self.store(message, responses)
		row = self.stored()
		self.assertTrue(row.attach.startswith("/private/files/"))
		self.assertTrue(row.attach.endswith(".png"))
		self.assertEqual(frappe.db.get_value("File", {"file_url": row.attach}, "is_private"), 1)
		self.assertEqual(get.call_args_list[0].kwargs["timeout"], guard.MEDIA_TIMEOUT)

	def test_a_rep_cannot_list_or_read_another_reps_media(self):
		lead = frappe.new_doc("CRM Lead")
		lead.update({"first_name": "Mine", "mobile_no": "0825550148", "lead_owner": self.reps[0]})
		lead.insert(ignore_permissions=True)
		message, responses = media()
		self.store(message, responses)
		file = frappe.db.get_value("File", {"file_url": self.stored().attach}, "name")
		frappe.set_user(self.reps[1])
		self.assertNotIn(
			file, frappe.get_list("File", filters={"attached_to_doctype": "WhatsApp Message"}, pluck="name")
		)
		self.assertFalse(frappe.get_doc("File", file).is_downloadable())
		frappe.set_user(self.reps[0])
		self.assertTrue(frappe.get_doc("File", file).is_downloadable())

	def test_public_upload_restriction_does_not_stop_media(self):
		frappe.db.set_single_value("System Settings", "only_allow_system_managers_to_upload_public_files", 1)
		frappe.clear_document_cache("System Settings", "System Settings")
		frappe.set_user("Guest")
		message, responses = media()
		self.store(message, responses)
		self.assertTrue(self.stored().attach)

	def test_a_codec_parameter_does_not_reach_the_filename(self):
		message, responses = media("audio", mime="audio/ogg; codecs=opus", content=b"OggS")
		self.store(message, responses)
		self.assertTrue(self.stored().attach.endswith(".ogg"))

	def test_a_meta_failure_leaves_a_note(self):
		message, _responses = media()
		self.store(message, [FakeResponse(status=500)])
		row = self.stored()
		self.assertEqual(row.content_type, "text")
		self.assertIn("could not be downloaded", row.message)

	def test_a_timeout_leaves_a_note(self):
		message, _responses = media("document", caption="Invoice")
		self.store(message, requests.Timeout("slow"))
		self.assertIn("Invoice", self.stored().message)

	def test_a_file_over_the_limit_leaves_a_note(self):
		message, responses = media()
		with patch.object(guard, "max_media_bytes", return_value=2):
			self.store(message, responses)
		self.assertIn("could not be downloaded", self.stored().message)

	def test_a_webhook_with_media_queues_it_and_returns_at_once(self):
		message, _responses = media()
		payload = inbound()
		payload["entry"][0]["changes"][0]["value"]["messages"] = [message]
		with patch.object(guard.frappe, "enqueue") as enqueue:
			self.assertEqual(self.post(payload).status_code, 200)
		self.assertEqual(enqueue.call_args.kwargs["job_id"], "whatsapp_media_wamid.media")
		self.assertFalse(self.rows(type="Incoming"))
		self.assertTrue(frappe.db.exists("CRM Lead", {"mobile_no": "+" + SENDER}))
		job = {
			k: v for k, v in enqueue.call_args.kwargs.items() if k in ("account", "message", "profile_name")
		}
		self.assertEqual(enqueue.call_args.args[0], "crm.integrations.whatsapp.webhook.store_media")
		with patch.object(guard.requests, "get", side_effect=media()[1]):
			guard.store_media(**job)
		frappe.set_user("Administrator")
		self.assertTrue(self.stored().attach)


class TestInbound(WhatsAppCase):
	def test_a_bare_contact_gets_a_lead_in_their_own_name(self):
		contact = frappe.new_doc("Contact")
		contact.update({"first_name": "Imported", "last_name": "Buyer", "company_name": "Acumatica Co"})
		contact.append("phone_nos", {"phone": "0825550148", "is_primary_mobile_no": 1})
		contact.insert(ignore_permissions=True)
		self.post(inbound())
		lead = frappe.get_all(
			"CRM Lead", filters={"source": "WhatsApp"}, fields=["first_name", "organization", "lead_owner"]
		)[0]
		self.assertEqual(
			(lead.first_name, lead.organization, lead.lead_owner), ("Imported", "Acumatica Co", self.reps[0])
		)

	def test_a_rep_is_required_on_a_line(self):
		line = frappe.new_doc("CRM WhatsApp Line")
		line.whatsapp_account = "Line A"
		with self.assertRaises(frappe.MandatoryError):
			line.insert(ignore_permissions=True)

	def test_a_known_number_lands_on_its_record(self):
		lead = frappe.new_doc("CRM Lead")
		lead.update({"first_name": "Known", "mobile_no": "082 555 0148"})
		lead.insert(ignore_permissions=True)
		self.post(inbound())
		row = self.rows(type="Incoming")[0]
		self.assertEqual((row.reference_doctype, row.reference_name), ("CRM Lead", lead.name))
		self.assertEqual(row.whatsapp_account, "Line A")

	def test_an_unknown_number_gets_one_lead_owned_by_the_receiving_rep(self):
		self.post(inbound())
		self.post(inbound(text="Second"))
		leads = frappe.get_all(
			"CRM Lead",
			filters={"mobile_no": "+" + SENDER},
			fields=["name", "lead_owner", "owner", "source", "first_name"],
		)
		self.assertEqual(len(leads), 1)
		lead = leads[0]
		self.assertEqual((lead.lead_owner, lead.owner, lead.source), (self.reps[0], self.reps[0], "WhatsApp"))
		self.assertEqual(lead.first_name, "Thandi")
		rows = self.rows(type="Incoming")
		self.assertEqual({row.reference_name for row in rows}, {lead.name})
		self.assertEqual(len(rows), 2)

	def test_the_receiving_rep_is_notified_though_not_assigned(self):
		lead = frappe.new_doc("CRM Lead")
		lead.update({"first_name": "Theirs", "mobile_no": "0825550148", "lead_owner": self.reps[1]})
		lead.insert(ignore_permissions=True)
		self.post(inbound())
		told = frappe.get_all(
			"CRM Notification",
			filters={"type": "WhatsApp", "to_user": ("in", self.reps)},
			fields=["to_user", "reference_name", "notification_text"],
		)
		by_user = {row.to_user: row for row in told}
		self.assertEqual(set(by_user), set(self.reps))
		self.assertEqual(by_user[self.reps[1]].reference_name, lead.name)
		self.assertFalse(by_user[self.reps[0]].reference_name)
		self.assertNotIn("Theirs", by_user[self.reps[0]].notification_text)

	def test_a_profile_name_cannot_carry_markup(self):
		self.post(inbound(name="<img src=x onerror=alert(1)>Sam"))
		lead = frappe.get_all("CRM Lead", filters={"source": "WhatsApp"}, pluck="lead_name")[0]
		self.assertNotIn("<", lead)

	def test_a_retried_delivery_is_stored_once(self):
		self.post(inbound(message_id="wamid.same"))
		self.post(inbound(message_id="wamid.same"))
		self.assertEqual(len(self.rows(message_id="wamid.same")), 1)

	def test_an_unsupported_type_becomes_a_note_and_not_a_failure(self):
		self.assertEqual(self.post(inbound(type="sticker", sticker={"id": "1"})).status_code, 200)
		self.assertIn("sticker", self.rows(type="Incoming")[0].message)

	def test_a_location_is_readable(self):
		self.post(inbound(type="location", location={"latitude": -26.2, "longitude": 28.04, "name": "Depot"}))
		self.assertIn("Depot", self.rows(type="Incoming")[0].message)

	def test_every_change_in_a_batch_is_processed(self):
		payload = inbound(text="one")
		payload["entry"][0]["changes"].append(
			inbound(number="27825550149", text="two")["entry"][0]["changes"][0]
		)
		self.post(payload)
		self.assertEqual(len(self.rows(type="Incoming")), 2)

	def test_a_status_callback_updates_the_message(self):
		self.post(inbound(message_id="wamid.status"))
		self.post(status("wamid.status", "read"))
		self.assertEqual(self.rows(message_id="wamid.status")[0].status, "read")

	def test_a_status_for_a_message_never_stored_is_ignored(self):
		self.assertEqual(self.post(status("wamid.unknown")).status_code, 200)

	def test_a_template_status_event_verifies_by_waba(self):
		payload = {
			"object": "whatsapp_business_account",
			"entry": [
				{
					"id": WABA,
					"changes": [
						{
							"field": "message_template_status_update",
							"value": {"event": "APPROVED", "message_template_id": 1},
						}
					],
				}
			],
		}
		self.assertEqual(self.post(payload).status_code, 200)


class TestSending(WhatsAppCase):
	def record(self, number="0825550148", owner=None):
		lead = frappe.new_doc("CRM Lead")
		lead.update({"first_name": "Buyer", "mobile_no": number, "lead_owner": owner or self.reps[0]})
		return lead.insert(ignore_permissions=True)

	def send(self, lead, message="Hi", **kwargs):
		with patch(
			"frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message.make_post_request",
			return_value={"messages": [{"id": "wamid.out" + frappe.generate_hash(length=6)}]},
		) as meta:
			name = create_whatsapp_message("CRM Lead", lead.name, message, **kwargs)
		return frappe.get_doc("WhatsApp Message", name), meta

	def test_a_rep_sends_from_their_own_number_to_a_normalised_destination(self):
		lead = self.record()
		frappe.set_user(self.reps[0])
		doc, meta = self.send(lead)
		frappe.set_user("Administrator")
		self.assertEqual((doc.whatsapp_account, doc.to, doc.type), ("Line A", SENDER, "Outgoing"))
		url = meta.call_args.args[0]
		self.assertIn(f"/{PHONE_A}/messages", url)
		self.assertEqual(json.loads(meta.call_args.kwargs["data"])["to"], SENDER)
		self.assertEqual(meta.call_args.kwargs["headers"]["authorization"], "Bearer token-" + PHONE_A)

	def test_the_request_cannot_choose_the_account(self):
		lead = self.record()
		frappe.set_user(self.reps[0])
		frappe.local.form_dict = frappe._dict(whatsapp_account="Line B")
		doc, _meta = self.send(lead)
		self.assertEqual(doc.whatsapp_account, "Line A")

	def test_a_rep_with_no_number_is_told_so(self):
		lead = self.record()
		frappe.set_user("Administrator")
		self.assertIsNone(get_sending_account("Administrator"))
		with self.assertRaisesRegex(frappe.ValidationError, "no active WhatsApp number"):
			self.send(lead)

	def test_the_default_is_a_fallback_only_when_it_is_nobodys_line(self):
		frappe.db.set_single_value("WhatsApp Settings", "default_outgoing_account", "Line B")
		self.assertIsNone(get_sending_account("Administrator"))
		frappe.delete_doc("CRM WhatsApp Line", "Line B", ignore_permissions=True)
		self.assertEqual(get_sending_account("Administrator"), "Line B")

	def test_an_inactive_number_cannot_send(self):
		frappe.db.set_value("WhatsApp Account", "Line A", "status", "Inactive")
		self.assertIsNone(get_sending_account(self.reps[0]))

	def test_can_send_is_per_rep_and_enabled_is_per_site(self):
		self.assertTrue(is_whatsapp_enabled())
		self.assertFalse(can_send_whatsapp())
		frappe.set_user(self.reps[0])
		self.assertTrue(can_send_whatsapp())
		frappe.set_user("Administrator")
		frappe.db.set_value("WhatsApp Account", {"status": "Active"}, "status", "Inactive")
		self.assertFalse(is_whatsapp_enabled())

	def test_an_empty_message_is_refused_before_meta(self):
		lead = self.record()
		frappe.set_user(self.reps[0])
		with self.assertRaisesRegex(frappe.ValidationError, "Type a message"):
			self.send(lead, message="   ")

	def test_a_number_that_is_real_to_meta_but_not_to_our_tables_can_be_answered(self):
		lead = self.record(number="+999 123 45678")
		frappe.set_user(self.reps[0])
		doc, _meta = self.send(lead)
		self.assertEqual(doc.to, "99912345678")

	def test_a_local_spelling_we_cannot_place_is_still_refused(self):
		lead = self.record(number="123")
		frappe.set_user(self.reps[0])
		with self.assertRaisesRegex(frappe.ValidationError, "not a valid phone number"):
			self.send(lead)

	def test_a_deals_lead_thread_names_the_sender_too(self):
		lead = self.record()
		frappe.set_user(self.reps[0])
		self.send(lead)
		frappe.set_user("Administrator")
		deal = frappe.new_doc("CRM Deal")
		deal.update({"lead": lead.name, "deal_owner": self.reps[0]})
		deal.insert(ignore_permissions=True, ignore_mandatory=True)
		messages = get_whatsapp_messages("CRM Deal", deal.name)
		self.assertEqual(messages[0]["from_name"], get_fullname(self.reps[0]))

	def test_a_reaction_uses_the_reacting_reps_number(self):
		lead = self.record()
		self.post(inbound())
		incoming = self.rows(type="Incoming")[0]
		frappe.set_user(self.reps[0])
		with patch(
			"frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message.make_post_request",
			return_value={"messages": [{"id": "wamid.react"}]},
		):
			name = react_on_whatsapp_message("👍", incoming.name)
		self.assertEqual(frappe.db.get_value("WhatsApp Message", name, "whatsapp_account"), "Line A")
		self.assertEqual(lead.name, incoming.reference_name)

	def test_the_thread_names_the_sender_and_never_a_credential(self):
		lead = self.record()
		frappe.set_user(self.reps[0])
		doc, _meta = self.send(lead)
		messages = get_whatsapp_messages("CRM Lead", lead.name)
		self.assertEqual(messages[0]["from_name"], get_fullname(self.reps[0]))
		dumped = json.dumps(messages, default=str)
		self.assertNotIn("token-", dumped)
		self.assertNotIn(SECRET, dumped)

	def test_a_rep_cannot_read_accounts_or_lines(self):
		frappe.set_user(self.reps[0])
		for doctype in ("WhatsApp Account", "CRM WhatsApp Line"):
			with self.assertRaises(frappe.PermissionError):
				frappe.get_list(doctype)
