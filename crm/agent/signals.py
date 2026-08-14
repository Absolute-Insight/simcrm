# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deterministic signal engine behind CRM Suggestion.

Detection functions are pure -- plain rows and a ``now`` in, suggestion dicts
out -- so thresholds live in tests, not in a running site. ``run_signals`` is
the only frappe-facing entry point: it expires stale suggestions, runs every
detector over batched queries (no per-record queries), drops candidates that
an open or recently-actioned suggestion already covers, and inserts the rest.

This layer is model-free by design (PLAN.md Phase 8, constraint 3): it must
work identically with the agent tier disabled. Nothing here may import
``crm.agent.client``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import frappe

IDLE_DEAL_DAYS = 7
DISMISS_COOLDOWN_DAYS = 14
SUGGESTION_TTL_DAYS = 14


def find_idle_deals(rows: list[dict], activity: dict[str, datetime], now: datetime) -> list[dict]:
	"""Open/ongoing deals with no recorded activity for IDLE_DEAL_DAYS.

	``activity`` maps deal name -> latest activity datetime; a deal absent from
	it falls back to its creation date, so a deal never touched still ages.
	"""
	out = []
	threshold = now - timedelta(days=IDLE_DEAL_DAYS)
	for row in rows:
		last = activity.get(row["name"]) or row["creation"]
		if last > threshold:
			continue
		idle_days = (now - last).days
		label = row.get("organization") or row["name"]
		out.append(
			{
				"signal": "idle_deal",
				"title": f"Re-engage {label}",
				"reference_doctype": "CRM Deal",
				"reference_docname": row["name"],
				"user": row.get("deal_owner"),
				"suggested_action": "create_task",
				"action_payload": {"title": f"Re-engage {label}"},
				"rationale": f"No activity on this deal for {idle_days} days.",
				"factors": {"idle_days": idle_days},
				"score": min(100.0, idle_days * 10.0),
			}
		)
	return out


def find_missing_next_step(rows: list[dict], open_tasks: set[str]) -> list[dict]:
	"""Open/ongoing deals with no open task and no ``next_step`` set."""
	out = []
	for row in rows:
		if row["name"] in open_tasks or (row.get("next_step") or "").strip():
			continue
		label = row.get("organization") or row["name"]
		out.append(
			{
				"signal": "no_next_step",
				"title": f"Set the next step for {label}",
				"reference_doctype": "CRM Deal",
				"reference_docname": row["name"],
				"user": row.get("deal_owner"),
				"suggested_action": "create_task",
				"action_payload": {"title": f"Plan the next step for {label}"},
				"rationale": "This deal has no open task and no next step recorded.",
				"factors": {"has_open_task": False, "has_next_step": False},
				"score": 40.0,
			}
		)
	return out


def find_sla_breached_leads(rows: list[dict], now: datetime) -> list[dict]:
	"""Leads with an SLA whose first response is overdue (or already Failed)."""
	out = []
	for row in rows:
		if not row.get("sla") or row.get("first_response_time"):
			continue
		overdue = row.get("response_by") and row["response_by"] < now
		if not (overdue or row.get("sla_status") == "Failed"):
			continue
		label = row.get("lead_name") or row["name"]
		out.append(
			{
				"signal": "lead_sla",
				"title": f"Respond to {label} now",
				"reference_doctype": "CRM Lead",
				"reference_docname": row["name"],
				"user": row.get("lead_owner"),
				"suggested_action": "create_task",
				"action_payload": {"title": f"Respond to {label}", "priority": "High"},
				"rationale": "The first-response SLA on this lead has been breached.",
				"factors": {"sla_status": row.get("sla_status")},
				"score": 80.0,
			}
		)
	return out


def dedupe(candidates: list[dict], existing: list[dict], now: datetime) -> list[dict]:
	"""Drop candidates already covered by an existing suggestion.

	Open suggestions always block. Dismissed and Accepted ones block for
	DISMISS_COOLDOWN_DAYS after their last change -- a rep who said "no" (or
	already acted) is not nagged about the same record twice in that window.
	Expired suggestions never block: the state persisting is the signal.
	"""
	cooldown = now - timedelta(days=DISMISS_COOLDOWN_DAYS)
	blocked = set()
	for row in existing:
		key = (row["signal"], row["reference_docname"])
		if row["status"] == "Open":
			blocked.add(key)
		elif row["status"] in ("Dismissed", "Accepted") and row["modified"] > cooldown:
			blocked.add(key)
	return [c for c in candidates if (c["signal"], c["reference_docname"]) not in blocked]


# --- frappe-facing layer -------------------------------------------------


def _working_deal_rows() -> list[dict]:
	statuses = frappe.get_all("CRM Deal Status", filters={"type": ("in", ("Open", "Ongoing"))}, pluck="name")
	if not statuses:
		return []
	return frappe.get_all(
		"CRM Deal",
		filters={"status": ("in", statuses)},
		fields=["name", "organization", "deal_owner", "next_step", "creation"],
	)


def _latest_activity(deal_names: list[str]) -> dict[str, datetime]:
	"""Latest touch per deal across every activity source, in four queries."""
	if not deal_names:
		return {}
	from frappe.query_builder.functions import Max

	latest: dict[str, datetime] = {}
	sources = (
		("Communication", "reference_name", "creation"),
		("CRM Task", "reference_docname", "modified"),
		("CRM Call Log", "reference_docname", "modified"),
		("Comment", "reference_name", "creation"),
	)
	for doctype, ref_field, when_field in sources:
		table = frappe.qb.DocType(doctype)
		ref = table[ref_field]
		query = (
			frappe.qb.from_(table)
			.select(ref.as_("ref"), Max(table[when_field]).as_("last"))
			.where(table.reference_doctype == "CRM Deal")
			.where(ref.isin(deal_names))
			.groupby(ref)
		)
		if doctype == "Comment":
			# only human comments count as activity — assignment/share/system
			# comments would reset the idle clock on every automation
			query = query.where(table.comment_type == "Comment")
		rows = query.run(as_dict=True)
		for row in rows:
			if row["last"] and (row["ref"] not in latest or row["last"] > latest[row["ref"]]):
				latest[row["ref"]] = row["last"]
	return latest


def _deals_with_open_tasks(deal_names: list[str]) -> set[str]:
	if not deal_names:
		return set()
	return set(
		frappe.get_all(
			"CRM Task",
			filters={
				"reference_doctype": "CRM Deal",
				"reference_docname": ("in", deal_names),
				"status": ("not in", ("Done", "Canceled")),
			},
			pluck="reference_docname",
		)
	)


def _sla_lead_rows() -> list[dict]:
	return frappe.get_all(
		"CRM Lead",
		filters={"converted": 0, "sla": ("is", "set")},
		fields=[
			"name",
			"lead_name",
			"lead_owner",
			"sla",
			"sla_status",
			"response_by",
			"first_response_time",
		],
	)


def expire_stale(now: datetime) -> None:
	stale = frappe.get_all(
		"CRM Suggestion",
		filters={"status": "Open", "expires_on": ("<", now)},
		pluck="name",
	)
	for name in stale:
		frappe.db.set_value("CRM Suggestion", name, "status", "Expired")


def run_signals() -> int:
	"""Scheduler entry point. Returns how many suggestions were created."""
	now = frappe.utils.now_datetime()
	expire_stale(now)

	deals = _working_deal_rows()
	deal_names = [d["name"] for d in deals]
	candidates = (
		find_idle_deals(deals, _latest_activity(deal_names), now)
		+ find_missing_next_step(deals, _deals_with_open_tasks(deal_names))
		+ find_sla_breached_leads(_sla_lead_rows(), now)
	)
	if not candidates:
		return 0

	existing = frappe.get_all(
		"CRM Suggestion",
		filters={"reference_docname": ("in", [c["reference_docname"] for c in candidates])},
		fields=["signal", "reference_docname", "status", "modified"],
	)
	fresh = dedupe(candidates, existing, now)

	expires_on = now + timedelta(days=SUGGESTION_TTL_DAYS)
	for candidate in fresh:
		doc = dict(
			candidate,
			doctype="CRM Suggestion",
			action_payload=json.dumps(candidate["action_payload"]),
			factors=json.dumps(candidate["factors"]),
			expires_on=expires_on,
		)
		frappe.get_doc(doc).insert(ignore_permissions=True)
	if fresh:
		frappe.db.commit()
	return len(fresh)
