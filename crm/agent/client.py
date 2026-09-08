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

from crm.agent.config import AgentConfig
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import json_schema, parse_into

MAX_ATTEMPTS = 2

# A reply is one JSON object of at most ``max_tokens`` tokens; anything past this
# is a proxy page, a misconfigured endpoint or a server that will not stop. Read
# in chunks this size so the wall-clock deadline is checked often.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 16 * 1024

RETRY_INSTRUCTION = (
	"Your previous reply was rejected: {error}. "
	"Reply with JSON matching the schema exactly, and nothing else."
)


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
	attempt_messages = list(messages)
	last_error = "no attempt was made"

	for _attempt in range(MAX_ATTEMPTS):
		timeout = _time_allowed(cfg, deadline)
		raw = _post(cfg, _request_body(cfg, schema, attempt_messages), timeout)
		try:
			return parse_into(model, raw)
		except SchemaMismatch as exc:
			last_error = str(exc)
			attempt_messages = [
				*messages,
				{"role": "user", "content": RETRY_INSTRUCTION.format(error=last_error)},
			]
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
			response.raise_for_status()
			raw = _read_bounded(cfg, response, deadline, timeout)
		finally:
			response.close()
		return _content(raw)
	except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
		raise AgentUnavailable(f"{cfg.base_url}: {exc}") from exc


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
