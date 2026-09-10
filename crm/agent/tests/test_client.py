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
	def test_invalid_reply_is_retried_once_with_the_error_and_the_reply_fed_back(self):
		replies = [_reply("Here you go!"), _reply(GOOD)]
		with mock.patch.object(client_mod.requests, "post", side_effect=replies) as post:
			result = client_mod.complete(CFG, ThreadSummary, MESSAGES)

		self.assertEqual(result.summary, "Deal is stalled on pricing.")
		self.assertEqual(post.call_count, 2)
		retry_messages = post.call_args_list[1][1]["json"]["messages"]
		# the rejected reply goes back as the assistant turn it was, then the
		# complaint: a model that cannot see what it got wrong repeats it
		self.assertEqual(len(retry_messages), len(MESSAGES) + 2)
		self.assertEqual(retry_messages[-2], {"role": "assistant", "content": "Here you go!"})
		self.assertIn("rejected", retry_messages[-1]["content"])

	def test_an_empty_reply_is_not_retried(self):
		"""Nothing came back, so there is nothing to correct. The retry used to be
		the same request again -- two round trips and two timeouts for one refusal."""
		with mock.patch.object(client_mod.requests, "post", return_value=_reply("")) as post:
			with self.assertRaises(SchemaMismatch):
				client_mod.complete(CFG, ThreadSummary, MESSAGES)
		self.assertEqual(post.call_count, 1)

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


class ClientDeadlineTest(UnitTestCase):
	"""A caller that makes more than one completion in a request (the Analyst)
	hands every call one absolute deadline, so the whole request -- retries
	included -- fits inside ``timeout x MAX_ATTEMPTS`` rather than each call
	being allowed that on its own."""

	def test_each_attempt_is_bounded_by_the_time_left_to_the_deadline(self):
		clock = iter([100.0, 100.0, 100.0, 100.0])
		with (
			mock.patch.object(client_mod.requests, "post", return_value=_reply(GOOD)) as post,
			mock.patch.object(client_mod.time, "monotonic", side_effect=lambda: next(clock)),
		):
			client_mod.complete(CFG, ThreadSummary, MESSAGES, deadline=102.0)
		# two seconds were left; the connect timeout must not be the full five
		self.assertEqual(post.call_args[1]["timeout"], 2.0)

	def test_a_call_started_after_the_deadline_is_refused_without_a_request(self):
		with (
			mock.patch.object(client_mod.requests, "post") as post,
			mock.patch.object(client_mod.time, "monotonic", return_value=200.0),
		):
			with self.assertRaises(AgentUnavailable) as caught:
				client_mod.complete(CFG, ThreadSummary, MESSAGES, deadline=199.0)
		post.assert_not_called()
		self.assertIn("deadline", str(caught.exception))

	def test_a_retry_past_the_deadline_is_not_attempted(self):
		# the first reply is unusable; by the time the retry would go out the
		# deadline has passed, so the retry is skipped and the schema error
		# is what the caller hears
		clock = iter([100.0, 100.0, 100.0, 100.0, 110.0, 110.0])
		with (
			mock.patch.object(client_mod.requests, "post", return_value=_reply("not json")) as post,
			mock.patch.object(client_mod.time, "monotonic", side_effect=lambda: next(clock)),
		):
			with self.assertRaises((SchemaMismatch, AgentUnavailable)):
				client_mod.complete(CFG, ThreadSummary, MESSAGES, deadline=105.0)
		self.assertEqual(post.call_count, 1)

	def test_without_a_deadline_the_configured_timeout_applies(self):
		with mock.patch.object(client_mod.requests, "post", return_value=_reply(GOOD)) as post:
			client_mod.complete(CFG, ThreadSummary, MESSAGES)
		self.assertEqual(post.call_args[1]["timeout"], CFG.timeout)


class PromptBudgetTest(UnitTestCase):
	"""#13: a prompt larger than the window is not an error anyone sees.

	Ollama truncates from the head -- the system instruction and the grounding --
	and answers 200; vLLM and llama.cpp answer 400 and the client called that
	"unreachable". Both are prevented by deciding the size before sending.
	"""

	def test_the_budget_is_the_window_less_the_reply(self):
		cfg = CFG.with_overrides(context_tokens=8192, max_tokens=2048)
		self.assertEqual(client_mod.prompt_budget(cfg), 8192 - 2048)
		self.assertEqual(
			client_mod.prompt_char_budget(cfg),
			int((8192 - 2048) * client_mod.prompting.CHARS_PER_TOKEN),
		)

	def test_a_window_smaller_than_the_reply_still_leaves_room_for_a_prompt(self):
		cfg = CFG.with_overrides(context_tokens=1024, max_tokens=2048)
		self.assertEqual(client_mod.prompt_budget(cfg), client_mod.MIN_PROMPT_TOKENS)

	def test_history_is_dropped_oldest_first_and_the_instruction_is_never_touched(self):
		cfg = CFG.with_overrides(context_tokens=1200, max_tokens=64)
		long_turn = "x" * 4000
		messages = [
			{"role": "system", "content": "SYSTEM INSTRUCTION"},
			{"role": "user", "content": f"oldest {long_turn}"},
			{"role": "assistant", "content": f"middle {long_turn}"},
			{"role": "user", "content": "the question"},
		]
		with mock.patch.object(client_mod.requests, "post", return_value=_reply(GOOD)) as post:
			client_mod.complete(cfg, ThreadSummary, messages)

		sent = post.call_args[1]["json"]["messages"]
		self.assertEqual(sent[0]["content"], "SYSTEM INSTRUCTION")
		self.assertEqual(sent[-1]["content"], "the question")
		self.assertNotIn("oldest", " ".join(m["content"] for m in sent))

	def test_a_prompt_that_already_fits_is_sent_unchanged(self):
		with mock.patch.object(client_mod.requests, "post", return_value=_reply(GOOD)) as post:
			client_mod.complete(CFG, ThreadSummary, MESSAGES)
		self.assertEqual(post.call_args[1]["json"]["messages"], MESSAGES)


class ContextLengthRefusalTest(UnitTestCase):
	"""#13: a 4xx that says the prompt did not fit gets its own exception."""

	BODIES = (
		b'{"error": {"message": "This model\'s maximum context length is 4096 tokens"}}',
		b'{"object":"error","message":"The prompt has too many tokens"}',
		b"Requested tokens exceed context window of 4096",
	)

	def _refusal(self, body: bytes, status_code: int = 400):
		response = mock.Mock()
		response.status_code = status_code
		response.raise_for_status.side_effect = requests.HTTPError("400 Client Error")
		response.iter_content.return_value = iter([body])
		return response

	def test_a_context_length_4xx_is_named_rather_than_reported_as_unreachable(self):
		for body in self.BODIES:
			with self.subTest(body=body):
				with mock.patch.object(client_mod.requests, "post", return_value=self._refusal(body)):
					with self.assertRaises(client_mod.ContextTooLong) as caught:
						client_mod.complete(CFG, ThreadSummary, MESSAGES)
				self.assertIsInstance(caught.exception, AgentUnavailable)
				self.assertIn("context window", str(caught.exception))

	def test_any_other_4xx_stays_an_ordinary_unavailable(self):
		with mock.patch.object(
			client_mod.requests, "post", return_value=self._refusal(b'{"error": "model not found"}', 404)
		):
			with self.assertRaises(AgentUnavailable) as caught:
				client_mod.complete(CFG, ThreadSummary, MESSAGES)
		self.assertNotIsInstance(caught.exception, client_mod.ContextTooLong)
