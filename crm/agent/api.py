# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Whitelisted entry points for agent features.

Returns a status rather than raising when the model is off or unreachable: an
unavailable endpoint should look like a feature that is not there, not like a bug.
Mirrors the shape of ``crm.domain_enrichment.api``, including its rule that every entry
point which triggers an outbound fetch is rate-limited per user.
"""

from __future__ import annotations

import frappe
from frappe.rate_limiter import rate_limit

from crm.agent import actions, client, tools
from crm.agent.config import get_config
from crm.agent.context import build_thread_messages
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import ThreadSummary

# Per-user, per-minute cap, matching ``domain_enrichment.api.ENRICH_RATE_LIMIT``.
# One call holds a worker for up to ``timeout`` x ``client.MAX_ATTEMPTS`` -- 60 seconds
# at the shipped defaults -- so without a cap a single authenticated user can occupy
# the whole worker pool from a loop. 10/min is far above any real human burst.
SUMMARISE_RATE_LIMIT = 10

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
