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
	# An inference server's port, not ours. This used to default to
	# localhost:8000/v1 -- frappe's own web port -- so an admin who enabled the
	# tier without editing it made the CRM POST to itself, collect a 404 and
	# report "unavailable" with nothing to suggest why. 11434 is ollama's
	# default and what the deploy stack's local-model profile serves, so the
	# default is now either correct or refused at connect, which reads honestly.
	"base_url": "http://localhost:11434/v1",
	"model": "lfm2.5-2.6b",
	"timeout": 30,
	"max_tokens": 1024,
	"daily_call_budget": 500,
}

# The deterministic tier's thresholds. Kept apart from DEFAULT_SETTINGS because they
# gate a feature that runs with the model off: an admin who never enables the agent
# still owns these numbers, and nothing here may make the signal job depend on the
# model tier's flag.
SIGNAL_DEFAULTS = {
	"signals_enabled": 1,
	"idle_deal_days": 7,
	"suggestion_ttl_days": 14,
	"dismiss_cooldown_days": 14,
	"close_horizon_days": 14,
	"max_open_per_user": 30,
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
	daily_call_budget: int = DEFAULT_SETTINGS["daily_call_budget"]
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
			daily_call_budget=to_int("daily_call_budget", DEFAULT_SETTINGS["daily_call_budget"]),
			api_key=str(merged.get("api_key") or ""),
		)


@dataclass(frozen=True)
class SignalConfig:
	"""Admin-tunable thresholds for the deterministic signal job.

	Every count is clamped to at least one: a zero threshold read from a
	half-filled Single would make the hourly job emit a suggestion for every
	record on the site, which is worse than any value an admin meant to type.
	The same clamp keeps a zero ``max_open_per_user`` from silencing the tier
	outright -- both ends of the range are a mistake, not a setting.
	"""

	signals_enabled: bool
	idle_deal_days: int
	suggestion_ttl_days: int
	dismiss_cooldown_days: int
	close_horizon_days: int
	max_open_per_user: int = SIGNAL_DEFAULTS["max_open_per_user"]

	@classmethod
	def from_settings(cls, settings: dict) -> SignalConfig:
		supplied = {k: v for k, v in (settings or {}).items() if v not in (None, "")}
		merged = {**SIGNAL_DEFAULTS, **supplied}

		def to_count(field):
			try:
				value = int(merged[field])
			except (ValueError, TypeError):
				_warn_discarded(field, merged[field])
				return SIGNAL_DEFAULTS[field]
			return max(1, value)

		try:
			signals_enabled = bool(int(merged["signals_enabled"]))
		except (ValueError, TypeError):
			_warn_discarded("signals_enabled", merged["signals_enabled"])
			signals_enabled = bool(SIGNAL_DEFAULTS["signals_enabled"])

		return cls(
			signals_enabled=signals_enabled,
			idle_deal_days=to_count("idle_deal_days"),
			suggestion_ttl_days=to_count("suggestion_ttl_days"),
			dismiss_cooldown_days=to_count("dismiss_cooldown_days"),
			close_horizon_days=to_count("close_horizon_days"),
			max_open_per_user=to_count("max_open_per_user"),
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


def get_signal_config() -> SignalConfig:
	"""Build a ``SignalConfig`` from the same Single. Never reads ``enabled``.

	The model flag and the signal flag are separate on purpose: turning the agent
	tier off must not silence the deterministic suggestions (PLAN.md Phase 8,
	constraint 3).

	Read through ``get_singles_dict`` rather than the cached document: ``as_dict()``
	coerces an Int field that was never saved to 0, so on a site whose admin has
	not opened the settings page the whole section would read as "signals off,
	every threshold zero" instead of falling back to SIGNAL_DEFAULTS.
	"""
	return SignalConfig.from_settings(frappe.db.get_singles_dict("CRM Agent Settings"))
