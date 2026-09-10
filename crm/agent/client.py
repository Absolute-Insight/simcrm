# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Talks to an OpenAI-compatible endpoint and returns validated objects.

``response_format: json_schema`` is used rather than a vendor-specific parameter, so
the same call works against vLLM, SGLang, llama.cpp and Ollama -- the whole point of
keeping the model replaceable. On vLLM this drives xgrammar-backed constrained
decoding, which is what makes a small model's output safe to parse at all.

One retry only: if a model that was *forced* into a schema still fails twice, the
prompt is wrong and burning tokens will not fix it.
"""

from __future__ import annotations

import json
import time

import requests
from pydantic import BaseModel

from crm.agent import prompting
from crm.agent.config import AgentConfig
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import json_schema, parse_into

MAX_ATTEMPTS = 2

# The floor under ``prompt_budget``. A window smaller than the reply budget is a
# misconfiguration, and answering it with "no room for a prompt at all" would
# turn a wrong number into a dead tier; leave enough for the instruction and let
# the endpoint be the one to complain.
MIN_PROMPT_TOKENS = 512

# How much of a rejected reply goes back to the model on the retry. Enough for it
# to see what it got wrong, bounded because the reply may be a proxy page.
RETRY_ECHO_CHARS = 2000

# A reply is one JSON object of at most ``max_tokens`` tokens; anything past this
# is a proxy page, a misconfigured endpoint or a server that will not stop. Read
# in chunks this size so the wall-clock deadline is checked often.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 16 * 1024

RETRY_INSTRUCTION = (
	"Your previous reply was rejected: {error}. "
	"Reply with JSON matching the schema exactly, and nothing else."
)


def prompt_budget(cfg: AgentConfig) -> int:
	"""Tokens the prompt may occupy: the context window, less the reply budget.

	The reply has to fit in the same window as the prompt. Sizing to the window
	alone leaves a prompt that fits and a reply that is cut off mid-JSON, which
	arrives as a ``SchemaMismatch`` and reads as a model that cannot follow a
	schema.
	"""
	return max(MIN_PROMPT_TOKENS, cfg.context_tokens - cfg.max_tokens)


def prompt_char_budget(cfg: AgentConfig) -> int:
	"""The same budget in characters, for the builders that measure in those."""
	return prompting.tokens_to_chars(prompt_budget(cfg))


def complete(
	cfg: AgentConfig, model: type[BaseModel], messages: list[dict], deadline: float | None = None
) -> BaseModel:
	"""Return a validated ``model`` instance, or raise.

	Raises ``AgentUnavailable`` on any transport problem and ``SchemaMismatch`` when
	the reply will not validate after one retry.

	``deadline`` is an absolute ``time.monotonic()`` value. A caller that makes
	more than one completion inside one web request (the Analyst: plan, then
	answer) passes the same deadline to each, so the request as a whole -- retries
	included -- fits inside ``timeout x MAX_ATTEMPTS`` instead of every call being
	allowed that on its own. Each attempt is then bounded by the time left, and an
	attempt that would start after the deadline is not made.
	"""
	schema = json_schema(model)
	budget = prompt_budget(cfg)
	# Last line of defence on prompt size. The builders size their own grounding
	# (only they know where the instruction ends), so what is usually dropped
	# here is history: a fourth follow-up used to push the system message out of
	# a 4k window, and ollama answers 200 to that rather than refusing it.
	messages = prompting.fit_messages(messages, budget)
	attempt_messages = messages
	last_error = "no attempt was made"

	for _attempt in range(MAX_ATTEMPTS):
		timeout = _time_allowed(cfg, deadline)
		raw = _post(cfg, _request_body(cfg, schema, attempt_messages), timeout)
		try:
			return parse_into(model, raw)
		except SchemaMismatch as exc:
			last_error = str(exc)
			if not str(raw or "").strip():
				# Nothing came back. "Your previous reply was rejected" with no
				# reply to point at is the *same* request again, which is what
				# an empty answer already refused; spend the second attempt only
				# when there is something for the model to correct.
				break
			attempt_messages = prompting.fit_messages(
				[
					*messages,
					# The rejected reply goes back with the complaint. Without it the
					# retry was a fresh request with an instruction appended, and a
					# model that cannot see what it got wrong repeats it.
					{"role": "assistant", "content": str(raw)[:RETRY_ECHO_CHARS]},
					{"role": "user", "content": RETRY_INSTRUCTION.format(error=last_error)},
				],
				budget,
			)
			if deadline is not None and time.monotonic() >= deadline:
				# the retry would be refused at _time_allowed anyway; say why
				# the reply was bad rather than that the clock ran out
				break

	raise SchemaMismatch(last_error)


def _time_allowed(cfg: AgentConfig, deadline: float | None) -> float:
	"""Seconds this attempt may take: ``cfg.timeout``, or less if the deadline is nearer."""
	if deadline is None:
		return cfg.timeout
	remaining = deadline - time.monotonic()
	if remaining <= 0:
		raise AgentUnavailable(f"{cfg.base_url}: request deadline passed before the call was made")
	return min(cfg.timeout, remaining)


def _request_body(cfg: AgentConfig, schema: dict, messages: list[dict]) -> dict:
	return {
		"model": cfg.model,
		"messages": messages,
		"max_tokens": cfg.max_tokens,
		"temperature": 0,
		"response_format": {
			"type": "json_schema",
			"json_schema": {"name": "output", "schema": schema, "strict": True},
		},
	}


class EndpointRejectedKey(AgentUnavailable):
	"""The endpoint answered 401/403: it is reachable, and the fix is ``api_key``."""


class ContextTooLong(AgentUnavailable):
	"""The endpoint refused the prompt as longer than the model's context window.

	Distinguished because it is the one transport failure that is not weather:
	the endpoint is up, and retrying the same question changes nothing. It means
	``context_tokens`` claims more room than the server actually serves --
	``num_ctx`` on ollama, ``--max-model-len`` on vLLM, ``-c`` on llama.cpp.
	Only servers that refuse get here; ollama truncates from the head and answers
	200, which is why the prompt is sized before it is sent rather than after.
	"""


# Substrings that mark a 4xx as "the prompt did not fit", across vLLM, llama.cpp,
# SGLang, TGI and the OpenAI API itself. Matched against a bounded slice of the
# error body, lower-cased. A miss costs nothing: the request is still an
# AgentUnavailable, just without the reason that names the fix.
CONTEXT_LENGTH_MARKERS = (
	"context length",
	"context_length",
	"context window",
	"context size",
	"too many tokens",
	"maximum context",
	"max_model_len",
	"max_seq_len",
	"prompt is too long",
	"reduce the length",
	"exceeds the model",
)

# How much of a 4xx body is read to classify it. The body is not echoed to any
# user; it goes to the error log where an admin reads it.
ERROR_BODY_BYTES = 2000


def _headers(cfg: AgentConfig) -> dict:
	"""Bearer auth only when a key is configured.

	An endpoint served with ``--api-key`` answers 401 without this, which would surface as
	an unexplained ``AgentUnavailable`` and no setting to fix it with.
	"""
	return {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}


def _post(cfg: AgentConfig, body: dict, timeout: float | None = None) -> str:
	"""One HTTP round trip, bounded by wall clock and by size.

	``requests``' ``timeout`` is a connect/inactivity timeout: a server that trickles
	a byte every few seconds never trips it. So the body is streamed under a deadline
	of ``timeout`` (``cfg.timeout`` unless the caller has less left) from the start
	of the call, and under ``MAX_RESPONSE_BYTES``, and either breach is an
	``AgentUnavailable`` like any other transport failure.
	"""
	timeout = cfg.timeout if timeout is None else timeout
	deadline = time.monotonic() + timeout
	try:
		response = requests.post(
			f"{cfg.base_url}/chat/completions",
			json=body,
			timeout=timeout,
			headers=_headers(cfg),
			stream=True,
			# a redirect would replay the configured Bearer token at whatever host
			# the response names, which is a credential leak the admin never agreed
			# to; an inference endpoint that redirects is misconfigured anyway
			allow_redirects=False,
		)
		try:
			if response.status_code in (401, 403):
				# distinguished so test_connection can point the admin at api_key
				# rather than at the URL; the body is not echoed, it may be anything
				raise EndpointRejectedKey(
					f"{cfg.base_url}: endpoint rejected the API key (HTTP {response.status_code})"
				)
			if 400 <= response.status_code < 500:
				detail = _error_body(response)
				if any(marker in detail.lower() for marker in CONTEXT_LENGTH_MARKERS):
					raise ContextTooLong(
						f"{cfg.base_url}: the prompt is longer than the model's context window "
						f"(HTTP {response.status_code}): {detail}"
					)
			response.raise_for_status()
			raw = _read_bounded(cfg, response, deadline, timeout)
		finally:
			response.close()
		return _content(raw)
	except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
		raise AgentUnavailable(f"{cfg.base_url}: {exc}") from exc


def _error_body(response) -> str:
	"""A bounded, decoded slice of an error response, for classification and the log.

	The body is streamed like any other, so it has to be read before
	``raise_for_status`` is allowed to throw it away -- and read with a ceiling,
	because a 4xx from a proxy is as likely to be a page as a JSON error.
	"""
	try:
		received = b""
		for chunk in response.iter_content(chunk_size=READ_CHUNK_BYTES):
			received += chunk or b""
			if len(received) >= ERROR_BODY_BYTES:
				break
		return received[:ERROR_BODY_BYTES].decode("utf-8", "replace")
	except Exception:
		return ""


def _read_bounded(cfg: AgentConfig, response, deadline: float, timeout: float) -> bytes:
	chunks: list[bytes] = []
	received = 0
	for chunk in response.iter_content(chunk_size=READ_CHUNK_BYTES):
		if not chunk:
			continue
		received += len(chunk)
		if received > MAX_RESPONSE_BYTES:
			raise AgentUnavailable(f"{cfg.base_url}: response exceeded {MAX_RESPONSE_BYTES} bytes")
		if time.monotonic() > deadline:
			raise AgentUnavailable(f"{cfg.base_url}: response not complete within {timeout:g}s")
		chunks.append(chunk)
	return b"".join(chunks)


def _content(raw: bytes) -> str:
	return json.loads(raw)["choices"][0]["message"]["content"]
