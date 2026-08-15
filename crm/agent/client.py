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

import requests
from pydantic import BaseModel

from crm.agent.config import AgentConfig
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import json_schema, parse_into

MAX_ATTEMPTS = 2

RETRY_INSTRUCTION = (
	"Your previous reply was rejected: {error}. "
	"Reply with JSON matching the schema exactly, and nothing else."
)


def complete(cfg: AgentConfig, model: type[BaseModel], messages: list[dict]) -> BaseModel:
	"""Return a validated ``model`` instance, or raise.

	Raises ``AgentUnavailable`` on any transport problem and ``SchemaMismatch`` when
	the reply will not validate after one retry.
	"""
	schema = json_schema(model)
	attempt_messages = list(messages)
	last_error = "no attempt was made"

	for _attempt in range(MAX_ATTEMPTS):
		raw = _post(cfg, _request_body(cfg, schema, attempt_messages))
		try:
			return parse_into(model, raw)
		except SchemaMismatch as exc:
			last_error = str(exc)
			attempt_messages = [
				*messages,
				{"role": "user", "content": RETRY_INSTRUCTION.format(error=last_error)},
			]

	raise SchemaMismatch(last_error)


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


def _headers(cfg: AgentConfig) -> dict:
	"""Bearer auth only when a key is configured.

	An endpoint served with ``--api-key`` answers 401 without this, which would surface as
	an unexplained ``AgentUnavailable`` and no setting to fix it with.
	"""
	return {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}


def _post(cfg: AgentConfig, body: dict) -> str:
	try:
		response = requests.post(
			f"{cfg.base_url}/chat/completions",
			json=body,
			timeout=cfg.timeout,
			headers=_headers(cfg),
			# a redirect would replay the configured Bearer token at whatever host
			# the response names, which is a credential leak the admin never agreed
			# to; an inference endpoint that redirects is misconfigured anyway
			allow_redirects=False,
		)
		response.raise_for_status()
		return response.json()["choices"][0]["message"]["content"]
	except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
		raise AgentUnavailable(f"{cfg.base_url}: {exc}") from exc
