# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Whitelisted entry points for agent features.

Returns a status rather than raising when the model is off or unreachable: an
unavailable endpoint should look like a feature that is not there, not like a bug.
Mirrors the shape of ``crm.domain_enrichment.api``, including its rule that every entry
point which triggers an outbound fetch is rate-limited per user.
"""

from __future__ import annotations

import time

import frappe
from frappe.rate_limiter import rate_limit

from crm.agent import actions, client, tools
from crm.agent.config import get_config, get_signal_config
from crm.agent.context import build_thread_messages
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import ConnectionProbe, ThreadSummary

# Per-user, per-minute cap, matching ``domain_enrichment.api.ENRICH_RATE_LIMIT``.
# One call holds a worker for up to ``timeout`` x ``client.MAX_ATTEMPTS`` -- 60 seconds
# at the shipped defaults -- so without a cap a single authenticated user can occupy
# the whole worker pool from a loop. 10/min is far above any real human burst.
SUMMARISE_RATE_LIMIT = 10

# Tighter than the feature endpoints: this is an admin pressing a button, not a
# rep working, and each press costs a full model call against someone's endpoint.
TEST_CONNECTION_RATE_LIMIT = 6

BUDGET_CACHE_KEY = "crm_agent_daily_calls"


def budget_key() -> str:
	"""Today's counter key, site-scoped.

	``incr`` and ``expire`` are raw redis commands and skip the site prefix that
	``get_value``/``set_value`` apply, so the site name goes in the key by hand or
	every site on the bench spends one shared budget.
	"""
	return f"{BUDGET_CACHE_KEY}:{frappe.local.site}:{frappe.utils.today()}"


def _budget_spent(cfg) -> bool:
	"""Count this call against the site-wide daily budget; True when it is gone.

	The per-user rate limit bounds a burst, not a day: fifty users at ten calls a
	minute is still an unbounded bill against whoever hosts the endpoint. The
	counter is a redis key per day, so it costs one incr and expires itself.
	"""
	if cfg.daily_call_budget <= 0:
		return False
	key = budget_key()
	try:
		spent = frappe.cache().incr(key)
		frappe.cache().expire(key, 60 * 60 * 36)
	except Exception:
		# a cache that is unavailable must not take the feature down with it
		return False
	return spent > cfg.daily_call_budget


@frappe.whitelist()
@rate_limit(limit=SUMMARISE_RATE_LIMIT, seconds=60)
def summarise_thread(reference_doctype: str, reference_name: str) -> dict:
	"""Summarise a record's communication thread.

	Returns ``{"status": "ok", "summary": {...}}`` on success, or a bare status of
	``disabled`` or ``unavailable``.
	"""
	cfg = get_config()
	if not cfg.enabled:
		return {"status": "disabled"}
	if _budget_spent(cfg):
		return {"status": "unavailable"}

	record = tools.read_record(reference_doctype, reference_name)
	thread = tools.read_thread(reference_doctype, reference_name)
	messages = build_thread_messages(record, thread)

	try:
		summary = client.complete(cfg, ThreadSummary, messages)
	except (AgentUnavailable, SchemaMismatch) as exc:
		frappe.log_error(title="CRM agent summary failed", message=str(exc))
		return {"status": "unavailable"}

	return {"status": "ok", "summary": summary.model_dump()}


@frappe.whitelist()
@rate_limit(limit=SUMMARISE_RATE_LIMIT, seconds=60)
def draft_reply(reference_doctype: str, reference_name: str) -> dict:
	"""Draft a reply to the latest inbound message on a record's thread.

	Returns ``{"status": "ok", "draft": {"subject", "body"}}`` or a bare degrade
	status. The draft is attacker-influenced text: the caller shows it in a
	compose window for a human to edit and send — it is never sent directly.
	"""
	cfg = get_config()
	if not cfg.enabled:
		return {"status": "disabled"}
	if _budget_spent(cfg):
		return {"status": "unavailable"}

	record = tools.read_record(reference_doctype, reference_name)
	thread = tools.read_thread(reference_doctype, reference_name)

	try:
		draft = actions.propose_reply(cfg, record, thread)
	except (AgentUnavailable, SchemaMismatch) as exc:
		frappe.log_error(title="CRM agent reply draft failed", message=str(exc))
		return {"status": "unavailable"}

	return {"status": "ok", "draft": draft.model_dump()}


@frappe.whitelist()
@rate_limit(limit=TEST_CONNECTION_RATE_LIMIT, seconds=60)
def test_connection() -> dict:
	"""Try the configured endpoint once and report exactly what happened.

	Until this existed the only way to learn that ``base_url`` was wrong was a rep
	clicking Summarise and getting a degraded dialog -- a failure that reaches a
	user before it reaches the admin who caused it.

	Runs the *real* path (:func:`client.complete` with a schema) rather than a
	bare HTTP ping, because reaching the host proves nothing about whether guided
	decoding works there, and that is the interesting failure.

	Deliberately works with ``enabled`` off, so an endpoint can be proved before
	it is switched on for reps. Reads the saved settings rather than anything the
	caller supplies: ``base_url`` is the target of a server-side POST carrying the
	API key, so accepting one over the wire would be an SSRF with credential
	replay, and the doctype's own validation is the only thing standing in front
	of it.
	"""
	frappe.only_for("System Manager", True)

	cfg = get_config()
	started = time.monotonic()
	try:
		client.complete(
			cfg,
			ConnectionProbe,
			[{"role": "user", "content": 'Reply with exactly {"ok": true}'}],
		)
	except AgentUnavailable as exc:
		# str(exc) is "<base_url>: <requests error>" -- no headers, so no key.
		return {
			"ok": False,
			"kind": "unreachable",
			"base_url": cfg.base_url,
			"model": cfg.model,
			"message": frappe._("Could not reach the endpoint: {0}").format(exc),
		}
	except SchemaMismatch as exc:
		return {
			"ok": False,
			"kind": "schema",
			"base_url": cfg.base_url,
			"model": cfg.model,
			"message": frappe._(
				"The endpoint answered but would not follow the response schema: {0}."
				" Check that {1} exists there and supports JSON schema output."
			).format(exc, cfg.model),
		}

	elapsed = time.monotonic() - started
	return {
		"ok": True,
		"kind": "ok",
		"base_url": cfg.base_url,
		"model": cfg.model,
		"latency_ms": round(elapsed * 1000),
		# A cold model can take ten times a warm one, so the number matters as
		# much as the verdict -- it is what the timeout has to clear.
		"message": frappe._("{0} answered in {1}s with a valid reply.").format(cfg.model, f"{elapsed:.1f}"),
	}


@frappe.whitelist()
def get_settings() -> dict:
	"""The settings actually in force, defaults filled in -- what the admin page must show.

	``frappe.client.get_value`` returns ``{}`` for a Single that has never been
	saved, so the settings page drew "Generate suggestions: off" and four blank
	thresholds while the signal job was in fact running happily on
	SIGNAL_DEFAULTS. Saving that screen then made the display true: every Check
	and Int the admin had never seen a value for was written as 0, which switched
	the whole suggestion engine off and collapsed all four thresholds. An admin
	configuring the model endpoint had no way to know they had just done that.

	So the page is handed the effective configuration rather than the stored rows,
	from the same dataclasses the job itself reads. ``api_key`` is not included:
	a Password field reads back masked and round-tripping it would write the mask.
	"""
	frappe.has_permission("CRM Agent Settings", "read", throw=True)

	cfg = get_config()
	signals = get_signal_config()
	return {
		"enabled": int(cfg.enabled),
		"base_url": cfg.base_url,
		"model": cfg.model,
		"timeout": cfg.timeout,
		"max_tokens": cfg.max_tokens,
		"daily_call_budget": cfg.daily_call_budget,
		"signals_enabled": int(signals.signals_enabled),
		"idle_deal_days": signals.idle_deal_days,
		"close_horizon_days": signals.close_horizon_days,
		"suggestion_ttl_days": signals.suggestion_ttl_days,
		"dismiss_cooldown_days": signals.dismiss_cooldown_days,
	}
