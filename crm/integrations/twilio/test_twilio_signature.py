# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Twilio webhooks were authenticated by an identifier, not a secret.

`validate_twilio_request` compared the `AccountSid` in the request body against
the configured one. An Account SID is not a credential: it appears in the Twilio
console, in dashboard URLs, and in the body of every webhook Twilio sends. Anyone
holding one could POST to `update_recording_info` and rewrite a call log's
`recording_url` to point a rep at audio of their choosing, or drive
`update_call_status_info` to rewrite call statuses.

Twilio's actual authentication is the `X-Twilio-Signature` header — an HMAC of
the URL and the sorted POST parameters, keyed with the account auth token —
and nothing checked it.

`RequestValidator` is deterministic, so these sign requests for real rather than
asserting against a recorded string.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from twilio.request_validator import RequestValidator

from crm.integrations.twilio.api import validate_twilio_signature

AUTH_TOKEN = "test-auth-token-0123456789abcdef"
URL = "https://crm.example.test/api/method/crm.integrations.twilio.api.update_recording_info"
PARAMS = {"AccountSid": "AC-not-a-secret", "CallSid": "CA123", "RecordingUrl": "https://x.test/a.mp3"}


def signature_for(url, params, token=AUTH_TOKEN):
	return RequestValidator(token).compute_signature(url, params)


class _FormDict(dict):
	"""werkzeug hands the view a MultiDict; only `to_dict` is used here."""

	def to_dict(self):
		return dict(self)


class FakeRequest:
	def __init__(self, url, params, headers):
		self.url = url
		self.form = _FormDict(params)
		self.headers = headers


def make_request(url, params, signature, extra_headers=None):
	headers = {"X-Twilio-Signature": signature}
	headers.update(extra_headers or {})
	return FakeRequest(url, params, headers)


class TwilioSignatureTest(IntegrationTestCase):
	def validate(self, request):
		with (
			patch("crm.integrations.twilio.api.get_decrypted_password", return_value=AUTH_TOKEN),
			patch.object(frappe, "request", request),
		):
			validate_twilio_signature()

	def test_a_correctly_signed_request_is_accepted(self):
		self.validate(make_request(URL, PARAMS, signature_for(URL, PARAMS)))

	def test_a_request_with_no_signature_is_refused(self):
		"""The whole attack: a forged POST carrying only the Account SID."""
		with self.assertRaises(frappe.PermissionError):
			self.validate(make_request(URL, PARAMS, ""))

	def test_a_tampered_parameter_is_refused(self):
		"""Signed for one recording URL, delivered with another."""
		signature = signature_for(URL, PARAMS)
		tampered = {**PARAMS, "RecordingUrl": "https://attacker.test/evil.mp3"}
		with self.assertRaises(frappe.PermissionError):
			self.validate(make_request(URL, tampered, signature))

	def test_a_signature_from_a_different_account_is_refused(self):
		other = signature_for(URL, PARAMS, token="a-different-account-token")
		with self.assertRaises(frappe.PermissionError):
			self.validate(make_request(URL, PARAMS, other))

	def test_a_signature_for_a_different_url_is_refused(self):
		elsewhere = signature_for(URL.replace("update_recording_info", "voice"), PARAMS)
		with self.assertRaises(frappe.PermissionError):
			self.validate(make_request(URL, PARAMS, elsewhere))

	def test_tls_termination_does_not_reject_a_valid_signature(self):
		"""Twilio signs https; behind a proxy the reconstructed URL can be http.
		Without the forwarded-scheme retry this rejects genuine webhooks, which
		is how a signature check gets disabled again a week after it ships."""
		proxied = URL.replace("https://", "http://")
		self.validate(
			make_request(
				proxied,
				PARAMS,
				signature_for(URL, PARAMS),
				extra_headers={"X-Forwarded-Proto": "https"},
			)
		)

	def test_an_unconfigured_auth_token_refuses_rather_than_allows(self):
		request = make_request(URL, PARAMS, signature_for(URL, PARAMS))
		with (
			patch("crm.integrations.twilio.api.get_decrypted_password", return_value=None),
			patch.object(frappe, "request", request),
			self.assertRaises(frappe.PermissionError),
		):
			validate_twilio_signature()
