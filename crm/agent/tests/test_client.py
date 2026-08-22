# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Client tests with the HTTP layer stubbed -- no network, no model, no GPU.

Covers the three behaviours that matter: the request carries a schema so the server
can constrain decoding, one bad reply is retried with the validation error fed back,
and any transport failure becomes ``AgentUnavailable`` so callers can degrade.
"""

from __future__ import annotations

from unittest import mock

import requests
from frappe.tests import UnitTestCase

from crm.agent import client as client_mod
from crm.agent.config import AgentConfig
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import ThreadSummary

CFG = AgentConfig(
	enabled=True,
	base_url="http://gpu.local:8000/v1",
	model="lfm2.5-2.6b",
	timeout=5,
	max_tokens=256,
)
MESSAGES = [{"role": "user", "content": "summarise"}]
GOOD = '{"summary": "Deal is stalled on pricing.", "next_steps": [], "sentiment": "negative"}'


def _reply(content: str, status_code: int = 200):
	"""A stubbed streaming response: the client reads ``iter_content``, not ``.json()``."""
	import json

	response = mock.Mock()
	response.status_code = status_code
	response.raise_for_status.return_value = None
	body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
	response.iter_content.return_value = iter([body])
	return response


class ClientRequestShapeTest(UnitTestCase):
	def test_request_sends_schema_and_deterministic_sampling(self):
		with mock.patch.object(client_mod.requests, "post", return_value=_reply(GOOD)) as post:
			result = client_mod.complete(CFG, ThreadSummary, MESSAGES)

		self.assertEqual(result.sentiment, "negative")
		url, kwargs = post.call_args[0][0], post.call_args[1]
		self.assertEqual(url, "http://gpu.local:8000/v1/chat/completions")
		self.assertEqual(kwargs["timeout"], 5)
		body = kwargs["json"]
		self.assertEqual(body["model"], "lfm2.5-2.6b")
		self.assertEqual(body["temperature"], 0)
		self.assertEqual(body["max_tokens"], 256)
		self.assertEqual(body["response_format"]["type"], "json_schema")
		self.assertIn("summary", body["response_format"]["json_schema"]["schema"]["properties"])


class ClientRetryTest(UnitTestCase):
	def test_invalid_reply_is_retried_once_with_the_error_fed_back(self):
		replies = [_reply("Here you go!"), _reply(GOOD)]
		with mock.patch.object(client_mod.requests, "post", side_effect=replies) as post:
			result = client_mod.complete(CFG, ThreadSummary, MESSAGES)

		self.assertEqual(result.summary, "Deal is stalled on pricing.")
		self.assertEqual(post.call_count, 2)
		retry_messages = post.call_args_list[1][1]["json"]["messages"]
		self.assertEqual(len(retry_messages), len(MESSAGES) + 1)
		self.assertIn("rejected", retry_messages[-1]["content"])

	def test_two_invalid_replies_raise_schema_mismatch(self):
		replies = [_reply("nope"), _reply("still nope")]
		with mock.patch.object(client_mod.requests, "post", side_effect=replies) as post:
			with self.assertRaises(SchemaMismatch):
				client_mod.complete(CFG, ThreadSummary, MESSAGES)

		self.assertEqual(post.call_count, client_mod.MAX_ATTEMPTS)

	def test_original_messages_are_not_mutated_by_the_retry(self):
		replies = [_reply("nope"), _reply(GOOD)]
		with mock.patch.object(client_mod.requests, "post", side_effect=replies):
			client_mod.complete(CFG, ThreadSummary, MESSAGES)

		self.assertEqual(MESSAGES, [{"role": "user", "content": "summarise"}])


class ClientTransportFailureTest(UnitTestCase):
	def test_timeout_becomes_agent_unavailable(self):
		with mock.patch.object(client_mod.requests, "post", side_effect=requests.Timeout("too slow")):
			with self.assertRaises(AgentUnavailable):
				client_mod.complete(CFG, ThreadSummary, MESSAGES)

	def test_unexpected_response_shape_becomes_agent_unavailable(self):
		broken = mock.Mock()
		broken.status_code = 200
		broken.raise_for_status.return_value = None
		broken.iter_content.return_value = iter([b'{"unexpected": true}'])
		with mock.patch.object(client_mod.requests, "post", return_value=broken):
			with self.assertRaises(AgentUnavailable):
				client_mod.complete(CFG, ThreadSummary, MESSAGES)

	def test_the_body_is_streamed_with_the_inactivity_timeout_still_set(self):
		with mock.patch.object(client_mod.requests, "post", return_value=_reply(GOOD)) as post:
			client_mod.complete(CFG, ThreadSummary, MESSAGES)
		self.assertTrue(post.call_args[1]["stream"])
		self.assertEqual(post.call_args[1]["timeout"], CFG.timeout)

	def test_a_reply_past_the_byte_ceiling_becomes_agent_unavailable(self):
		"""A trickling server never trips requests' inactivity timeout, and a server
		that will not stop never ends the body; both have to be cut off here."""
		huge = mock.Mock()
		huge.status_code = 200
		huge.raise_for_status.return_value = None
		chunk = b"x" * client_mod.READ_CHUNK_BYTES
		huge.iter_content.return_value = iter([chunk] * (client_mod.MAX_RESPONSE_BYTES // len(chunk) + 2))
		with mock.patch.object(client_mod.requests, "post", return_value=huge):
			with self.assertRaises(AgentUnavailable) as caught:
				client_mod.complete(CFG, ThreadSummary, MESSAGES)
		self.assertIn("exceeded", str(caught.exception))
		huge.close.assert_called()

	def test_a_body_that_outlives_the_wall_clock_deadline_becomes_agent_unavailable(self):
		slow = mock.Mock()
		slow.status_code = 200
		slow.raise_for_status.return_value = None
		slow.iter_content.return_value = iter([b"{", b'"choices": []}'])
		clock = iter([100.0, 100.0 + CFG.timeout + 1, 100.0 + CFG.timeout + 2])
		with (
			mock.patch.object(client_mod.requests, "post", return_value=slow),
			mock.patch.object(client_mod.time, "monotonic", side_effect=lambda: next(clock)),
		):
			with self.assertRaises(AgentUnavailable) as caught:
				client_mod.complete(CFG, ThreadSummary, MESSAGES)
		self.assertIn("not complete within", str(caught.exception))

	def test_a_rejected_key_is_named_as_such(self):
		"""401/403 means the host is reachable and the fix is the api_key field, so
		the admin's test_connection must be able to tell it from a dead port."""
		for status in (401, 403):
			with mock.patch.object(client_mod.requests, "post", return_value=_reply("", status_code=status)):
				with self.assertRaises(client_mod.EndpointRejectedKey) as caught:
					client_mod.complete(CFG, ThreadSummary, MESSAGES)
			self.assertIn("rejected the API key", str(caught.exception))
			self.assertIsInstance(caught.exception, AgentUnavailable)
