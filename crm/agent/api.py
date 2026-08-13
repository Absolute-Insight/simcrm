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

from crm.agent import client, tools
from crm.agent.config import get_config
from crm.agent.context import build_thread_messages
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import ThreadSummary

# Per-user, per-minute cap, matching ``domain_enrichment.api.ENRICH_RATE_LIMIT``.
# One call holds a worker for up to ``timeout`` x ``client.MAX_ATTEMPTS`` -- 60 seconds
# at the shipped defaults -- so without a cap a single authenticated user can occupy
# the whole worker pool from a loop. 10/min is far above any real human burst.
SUMMARISE_RATE_LIMIT = 10


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

	record = tools.read_record(reference_doctype, reference_name)
	thread = tools.read_thread(reference_doctype, reference_name)
	messages = build_thread_messages(record, thread)

	try:
		summary = client.complete(cfg, ThreadSummary, messages)
	except (AgentUnavailable, SchemaMismatch) as exc:
		frappe.log_error(title="CRM agent summary failed", message=str(exc))
		return {"status": "unavailable"}

	return {"status": "ok", "summary": summary.model_dump()}
