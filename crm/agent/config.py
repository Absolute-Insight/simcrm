# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Loads agent configuration from the desk.

Mirrors ``crm.domain_enrichment.config``: admin-edited settings are read here and
normalised into a plain dataclass, so nothing downstream touches the database.
``from_settings`` is deliberately dict-in so the client and its tests need no site.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe

# Applied when the Single doctype has never been saved -- the JSON field defaults only
# populate a freshly-created row, which may not exist yet.
DEFAULT_SETTINGS = {
	"enabled": 0,
	"base_url": "http://localhost:8000/v1",
	"model": "lfm2.5-2.6b",
	"timeout": 30,
	"max_tokens": 1024,
}


@dataclass(frozen=True)
class AgentConfig:
	enabled: bool
	base_url: str
	model: str
	timeout: int
	max_tokens: int

	@classmethod
	def from_settings(cls, settings: dict) -> AgentConfig:
		supplied = {k: v for k, v in (settings or {}).items() if v not in (None, "")}
		merged = {**DEFAULT_SETTINGS, **supplied}

		def to_int(value, default):
			try:
				return int(value)
			except (ValueError, TypeError):
				return default

		return cls(
			# Also via to_int: this module's contract is to degrade, never to raise, and a
			# bare int() on a hand-edited or fixture-supplied value ("yes") threw a
			# ValueError straight out of get_config().
			enabled=bool(to_int(merged["enabled"], DEFAULT_SETTINGS["enabled"])),
			base_url=str(merged["base_url"]).rstrip("/"),
			model=str(merged["model"]),
			timeout=to_int(merged["timeout"], DEFAULT_SETTINGS["timeout"]),
			max_tokens=to_int(merged["max_tokens"], DEFAULT_SETTINGS["max_tokens"]),
		)


def get_config() -> AgentConfig:
	"""Build an ``AgentConfig`` from the Settings Single. Cached per request by frappe."""
	settings = frappe.get_cached_doc("CRM Agent Settings").as_dict()
	return AgentConfig.from_settings(settings)
