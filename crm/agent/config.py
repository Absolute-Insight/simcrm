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


def _warn_discarded(field: str, value) -> None:
	"""Say so when a value is thrown away.

	Degrading silently means an admin who fat-fingers a timeout gets the default and no
	signal that their entry was ignored. Wrapped because ``from_settings`` is also called
	from pure tests with no site bootstrapped, and a logger that is unavailable must not
	turn a defaulted value into an exception -- that would undo the degradation this
	function exists to report.
	"""
	try:
		frappe.logger("crm.agent").warning(
			f"CRM Agent Settings.{field}: discarded uninterpretable value {value!r}, using the default"
		)
	except Exception:
		pass


@dataclass(frozen=True)
class AgentConfig:
	enabled: bool
	base_url: str
	model: str
	timeout: int
	max_tokens: int
	api_key: str = ""

	@classmethod
	def from_settings(cls, settings: dict) -> AgentConfig:
		supplied = {k: v for k, v in (settings or {}).items() if v not in (None, "")}
		merged = {**DEFAULT_SETTINGS, **supplied}

		def to_int(field, default):
			value = merged[field]
			try:
				return int(value)
			except (ValueError, TypeError):
				_warn_discarded(field, value)
				return default

		return cls(
			# Also via to_int: this module's contract is to degrade, never to raise, and a
			# bare int() on a hand-edited or fixture-supplied value ("yes") threw a
			# ValueError straight out of get_config().
			enabled=bool(to_int("enabled", DEFAULT_SETTINGS["enabled"])),
			base_url=str(merged["base_url"]).rstrip("/"),
			model=str(merged["model"]),
			timeout=to_int("timeout", DEFAULT_SETTINGS["timeout"]),
			max_tokens=to_int("max_tokens", DEFAULT_SETTINGS["max_tokens"]),
			api_key=str(merged.get("api_key") or ""),
		)


def get_config() -> AgentConfig:
	"""Build an ``AgentConfig`` from the Settings Single. Cached per request by frappe."""
	doc = frappe.get_cached_doc("CRM Agent Settings")
	settings = doc.as_dict()
	# A Password field comes back encrypted from as_dict(); get_password decrypts it. It
	# is absent rather than empty on a Single that has never been saved, hence the guard.
	try:
		settings["api_key"] = doc.get_password("api_key", raise_exception=False) or ""
	except Exception:
		settings["api_key"] = ""
	return AgentConfig.from_settings(settings)
