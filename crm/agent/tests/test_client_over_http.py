# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Transport tests against a real HTTP server on loopback.

Every other client test patches ``requests.post``, which proves the retry logic and the
error funnelling but never the wire: the URL that gets built, the headers that actually
travel, the JSON the server actually receives, the timeout reaching the socket. A mock
would happily accept a request no server could answer.

So this spins up a throwaway OpenAI-shaped handler on an ephemeral port and lets the
client make genuine requests to it. It is still not a model -- it is a socket that
answers like one -- but it closes the gap between "our mock agreed with us" and "an HTTP
server on the other end understood us". No external network is touched: the listener is
bound to 127.0.0.1 and torn down with the test.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

from frappe.tests import UnitTestCase

from crm.agent import client as client_mod
from crm.agent.config import AgentConfig
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import ThreadSummary

MESSAGES = [{"role": "user", "content": "summarise"}]
GOOD_CONTENT = '{"summary": "Stalled on pricing.", "next_steps": ["Send quote"], "sentiment": "negative"}'


def _completion(content: str) -> dict:
	"""The shape an OpenAI-compatible server returns."""
	return {"choices": [{"message": {"content": content}}]}


class _Handler(BaseHTTPRequestHandler):
	"""Serves queued replies and records what it was asked."""

	# Replaced per-test on a fresh subclass, so no two tests share state.
	replies: ClassVar[list] = []
	seen: ClassVar[list] = []

	def do_POST(self):
		length = int(self.headers.get("Content-Length") or 0)
		raw_body = self.rfile.read(length) if length else b"{}"
		type(self).seen.append(
			{
				"path": self.path,
				"headers": {k.lower(): v for k, v in self.headers.items()},
				"body": json.loads(raw_body or b"{}"),
			}
		)
		status, payload = (
			type(self).replies.pop(0) if type(self).replies else (500, {"error": "no reply queued"})
		)
		body = json.dumps(payload).encode()
		self.send_response(status)
		if payload.get("location"):
			self.send_header("Location", payload["location"])
		self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, *args, **kwargs):
		"""Silence the default stderr logging -- test output stays pristine."""


class HttpTransportTest(UnitTestCase):
	def setUp(self):
		# A fresh handler subclass per test keeps the reply queue and the request log
		# isolated without any cross-test cleanup.
		self.handler = type("_TestHandler", (_Handler,), {"replies": [], "seen": []})
		self.server = HTTPServer(("127.0.0.1", 0), self.handler)
		self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
		self.thread.start()
		self.addCleanup(self.thread.join, 5)
		self.addCleanup(self.server.server_close)
		self.addCleanup(self.server.shutdown)

	def _cfg(self, **overrides) -> AgentConfig:
		port = self.server.server_address[1]
		defaults = {
			"enabled": True,
			"base_url": f"http://127.0.0.1:{port}/v1",
			"model": "stub-model",
			"timeout": 10,
			"max_tokens": 128,
			"api_key": "",
		}
		return AgentConfig(**{**defaults, **overrides})

	def test_a_real_request_reaches_the_expected_path_and_returns_a_parsed_object(self):
		self.handler.replies.append((200, _completion(GOOD_CONTENT)))

		result = client_mod.complete(self._cfg(), ThreadSummary, MESSAGES)

		self.assertEqual(result.sentiment, "negative")
		self.assertEqual(result.next_steps, ["Send quote"])
		self.assertEqual(len(self.handler.seen), 1)
		self.assertEqual(self.handler.seen[0]["path"], "/v1/chat/completions")

	def test_the_server_receives_the_guided_decoding_schema(self):
		"""The whole reason a small model is usable here. If this body is wrong, the server
		samples freely and the retry loop becomes the only defence."""
		self.handler.replies.append((200, _completion(GOOD_CONTENT)))

		client_mod.complete(self._cfg(), ThreadSummary, MESSAGES)

		body = self.handler.seen[0]["body"]
		self.assertEqual(body["model"], "stub-model")
		self.assertEqual(body["temperature"], 0)
		self.assertEqual(body["max_tokens"], 128)
		schema = body["response_format"]["json_schema"]["schema"]
		self.assertEqual(body["response_format"]["type"], "json_schema")
		self.assertEqual(set(schema["required"]), set(schema["properties"]))
		self.assertFalse(schema["additionalProperties"])

	def test_an_api_key_arrives_as_a_bearer_header(self):
		self.handler.replies.append((200, _completion(GOOD_CONTENT)))

		client_mod.complete(self._cfg(api_key="s3cret"), ThreadSummary, MESSAGES)

		self.assertEqual(self.handler.seen[0]["headers"]["authorization"], "Bearer s3cret")

	def test_no_api_key_sends_no_authorization_header(self):
		"""A local server started without a key must not receive one."""
		self.handler.replies.append((200, _completion(GOOD_CONTENT)))

		client_mod.complete(self._cfg(), ThreadSummary, MESSAGES)

		self.assertNotIn("authorization", self.handler.seen[0]["headers"])

	def test_the_retry_crosses_the_wire_with_the_validation_error(self):
		self.handler.replies.append((200, _completion("Sure! Here is your summary.")))
		self.handler.replies.append((200, _completion(GOOD_CONTENT)))

		result = client_mod.complete(self._cfg(), ThreadSummary, MESSAGES)

		self.assertEqual(result.summary, "Stalled on pricing.")
		self.assertEqual(len(self.handler.seen), 2)
		retry_messages = self.handler.seen[1]["body"]["messages"]
		self.assertEqual(len(retry_messages), len(MESSAGES) + 1)
		self.assertIn("rejected", retry_messages[-1]["content"])

	def test_two_unusable_replies_raise_schema_mismatch(self):
		self.handler.replies.append((200, _completion("nope")))
		self.handler.replies.append((200, _completion("still nope")))

		with self.assertRaises(SchemaMismatch):
			client_mod.complete(self._cfg(), ThreadSummary, MESSAGES)

		self.assertEqual(len(self.handler.seen), client_mod.MAX_ATTEMPTS)

	def test_a_server_error_becomes_agent_unavailable(self):
		self.handler.replies.append((500, {"error": "boom"}))

		with self.assertRaises(AgentUnavailable):
			client_mod.complete(self._cfg(), ThreadSummary, MESSAGES)

	def test_an_unauthorised_server_becomes_agent_unavailable(self):
		"""What an endpoint started with --api-key returns when the key is missing. Worth
		pinning because the fix is a setting, not a code change."""
		self.handler.replies.append((401, {"error": "missing api key"}))

		with self.assertRaises(AgentUnavailable):
			client_mod.complete(self._cfg(), ThreadSummary, MESSAGES)

	def test_a_reply_that_is_not_json_becomes_agent_unavailable(self):
		"""A proxy or a wrong base_url answers with HTML, not a completion."""
		self.handler.replies.append((200, {"unexpected": "shape"}))

		with self.assertRaises(AgentUnavailable):
			client_mod.complete(self._cfg(), ThreadSummary, MESSAGES)

	def test_an_unreachable_endpoint_becomes_agent_unavailable(self):
		"""The state the endpoint reports as "unavailable" in production: nothing listening."""
		self.server.shutdown()
		self.server.server_close()

		with self.assertRaises(AgentUnavailable):
			client_mod.complete(self._cfg(timeout=2), ThreadSummary, MESSAGES)

	def test_a_redirect_is_not_followed_and_never_replays_the_key(self):
		"""A redirect would hand the configured Bearer token to whatever host the
		response names -- an SSRF with credential replay, from a Data field an admin
		filled in once. An inference endpoint that redirects is misconfigured anyway."""
		elsewhere = type("_RedirectTargetHandler", (_Handler,), {"replies": [], "seen": []})
		target = HTTPServer(("127.0.0.1", 0), elsewhere)
		thread = threading.Thread(target=target.serve_forever, daemon=True)
		thread.start()
		self.addCleanup(thread.join, 5)
		self.addCleanup(target.server_close)
		self.addCleanup(target.shutdown)
		elsewhere.replies.append((200, _completion(GOOD_CONTENT)))

		port = target.server_address[1]
		self.handler.replies.append((307, {"location": f"http://127.0.0.1:{port}/v1/chat/completions"}))
		self.handler.replies.append((200, _completion(GOOD_CONTENT)))

		with self.assertRaises(AgentUnavailable):
			client_mod.complete(self._cfg(api_key="s3cret"), ThreadSummary, MESSAGES)

		self.assertEqual(elsewhere.seen, [])
