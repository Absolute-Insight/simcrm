# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deal-health scoring — explainable by construction.

``score_deal`` is a transparent heuristic over structured features only
(PLAN.md Phase 8, constraint 2: never message text). It starts at 100 and
subtracts named, weighted factors; the factors list always accounts exactly
for the deduction, so the UI can show *why* a deal scores what it does.
The model tier, when enabled, may re-rank or annotate — it never replaces
this number silently.

Model-free like ``signals``: this module must not import ``crm.agent.client``.
"""

from __future__ import annotations

import frappe

IDLE_GRACE_DAYS = 3
STAGE_GRACE_DAYS = 21


def score_deal(features: dict) -> dict:
	"""Score 0-100 with factor attribution.

	Expected feature keys (missing/None values are treated as unknown and
	never punished): ``idle_days``, ``days_in_stage``, ``days_to_close``
	(negative = past due), ``has_open_task``, ``inbound_ratio``.
	"""
	factors = []

	idle_days = features.get("idle_days")
	if idle_days is not None and idle_days > IDLE_GRACE_DAYS:
		factors.append(
			{
				"key": "idle",
				"label": f"No activity for {idle_days} days",
				"weight": min(50, (idle_days - IDLE_GRACE_DAYS) * 4),
			}
		)

	days_in_stage = features.get("days_in_stage")
	if days_in_stage is not None and days_in_stage > STAGE_GRACE_DAYS:
		factors.append(
			{
				"key": "stage_stagnation",
				"label": f"In the same stage for {days_in_stage} days",
				"weight": min(20, days_in_stage - STAGE_GRACE_DAYS),
			}
		)

	days_to_close = features.get("days_to_close")
	if days_to_close is not None and days_to_close < 0:
		overdue = -days_to_close
		factors.append(
			{
				"key": "close_overdue",
				"label": f"Expected close date passed {overdue} days ago",
				"weight": min(30, 10 + overdue),
			}
		)

	if features.get("has_open_task") is False:
		factors.append(
			{
				"key": "no_open_task",
				"label": "No open task scheduled",
				"weight": 15,
			}
		)

	inbound_ratio = features.get("inbound_ratio")
	if inbound_ratio is not None and inbound_ratio <= 0.05:
		factors.append(
			{
				"key": "no_inbound",
				"label": "Conversation is one-sided — no inbound responses",
				"weight": 10,
			}
		)

	score = max(0, 100 - sum(f["weight"] for f in factors))
	return {"score": score, "factors": factors}


@frappe.whitelist()
def get_deal_health(name: str) -> dict:
	"""Feature extraction + scoring for one deal, permission-checked."""
	from crm.agent.signals import _latest_activity

	deal = frappe.get_doc("CRM Deal", name)
	deal.check_permission("read")
	now = frappe.utils.now_datetime()

	last = _latest_activity([name]).get(name) or deal.creation
	idle_days = max(0, (now - last).days)

	days_in_stage = None
	if deal.status_change_log:
		days_in_stage = max(0, (now - deal.status_change_log[-1].to_date).days)

	days_to_close = None
	if deal.closed_date:
		days_to_close = (deal.closed_date - now.date()).days

	has_open_task = bool(
		frappe.get_all(
			"CRM Task",
			filters={
				"reference_doctype": "CRM Deal",
				"reference_docname": name,
				"status": ("not in", ("Done", "Canceled")),
			},
			limit=1,
		)
	)

	comms = frappe.get_all(
		"Communication",
		filters={"reference_doctype": "CRM Deal", "reference_name": name},
		fields=["sent_or_received"],
		limit_page_length=200,
	)
	inbound_ratio = None
	if comms:
		inbound = sum(1 for c in comms if c.sent_or_received == "Received")
		inbound_ratio = inbound / len(comms)

	return score_deal(
		{
			"idle_days": idle_days,
			"days_in_stage": days_in_stage,
			"days_to_close": days_to_close,
			"has_open_task": has_open_task,
			"inbound_ratio": inbound_ratio,
		}
	)
