# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Typed outputs, and the JSON Schema handed to the model for guided decoding.

pydantic is available as a hard dependency of frappe -- do not re-declare it in
pyproject.toml (same reasoning as the beautifulsoup4 note there).

``extra="forbid"`` matters more than it looks: a small model that invents a key is
telling you the prompt is ambiguous, and silently dropping it hides that.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from crm.agent.errors import SchemaMismatch

MAX_NEXT_STEPS = 5


class ThreadSummary(BaseModel):
	model_config = ConfigDict(extra="forbid")

	summary: str = Field(min_length=1, max_length=1200)
	next_steps: list[str] = Field(default_factory=list, max_length=MAX_NEXT_STEPS)
	sentiment: Literal["positive", "neutral", "negative"] = "neutral"


class ConnectionProbe(BaseModel):
	"""The smallest reply that proves an endpoint is actually usable.

	Deliberately schema-constrained rather than a bare ping: reaching the host
	says nothing about whether guided decoding works there, and that is the
	failure this test exists to find. MiniCPM5-1B, for one, connects fine and
	returns empty content.
	"""

	model_config = ConfigDict(extra="forbid")

	ok: bool


class ReplyDraft(BaseModel):
	"""A reply the rep can edit and send. A draft, never a sent message."""

	model_config = ConfigDict(extra="forbid")

	subject: str = Field(min_length=1, max_length=200)
	body: str = Field(min_length=1, max_length=4000)


def json_schema(model: type[BaseModel]) -> dict:
	"""The schema to send as ``response_format``. Derived, never hand-written.

	Every property is marked required before the schema goes out. Strict-mode
	implementations of ``response_format: json_schema`` reject a schema whose
	``required`` list is not the full property set, and pydantic omits any field that
	has a default -- here ``next_steps`` and ``sentiment``. The model is then obliged to
	emit all three keys, which is what we wanted anyway: a field quietly absent from the
	reply is indistinguishable from a field the model had nothing to say about.
	"""
	schema = model.model_json_schema()
	if "properties" in schema:
		schema["required"] = list(schema["properties"])
	return schema


def parse_into(model: type[BaseModel], raw: str) -> BaseModel:
	"""Validate a raw model reply. Raises ``SchemaMismatch`` with a usable message."""
	try:
		return model.model_validate_json(raw)
	except ValidationError as exc:
		raise SchemaMismatch(_summarise_errors(exc)) from exc
	except (TypeError, json.JSONDecodeError) as exc:
		raise SchemaMismatch(f"reply was not JSON: {exc}") from exc


def _summarise_errors(exc: ValidationError) -> str:
	"""Compact, field-scoped text -- short enough to put back in a retry prompt."""
	parts = []
	for error in exc.errors():
		location = ".".join(str(piece) for piece in error["loc"]) or "(root)"
		parts.append(f"{location}: {error['msg']}")
	return "; ".join(parts)
