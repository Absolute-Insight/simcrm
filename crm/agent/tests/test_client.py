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


def _reply(content: str):
	response = mock.Mock()
	response.raise_for_status.return_value = None
	response.json.return_value = {"choices": [{"message": {"content": content}}]}
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
		broken.raise_for_status.return_value = None
		broken.json.return_value = {"unexpected": True}
		with mock.patch.object(client_mod.requests, "post", return_value=broken):
			with self.assertRaises(AgentUnavailable):
				client_mod.complete(CFG, ThreadSummary, MESSAGES)
