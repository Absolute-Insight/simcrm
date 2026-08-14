# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Rep-plan endpoints.

Managers can read any plan; everyone edits only their own. ``propose_week``
returns drafts only — the rep reviews and saves explicitly, which is the
Phase 8 write-gate rule applied to planning: agent-proposed items become
records only after a human confirms them.
"""

from __future__ import annotations

import json
from datetime import timedelta

import frappe
from frappe import _

ITEM_FIELDS = (
	"activity_type",
	"planned_date",
	"note",
	"reference_doctype",
	"reference_docname",
	"status",
	"fulfilled_by_doctype",
	"fulfilled_by",
	"suggestion",
)

ACTION_TO_ACTIVITY = {
	"create_task": "Task",
	"schedule_call": "Call",
	"send_reply": "Email",
	"update_field": "Task",
}


def _is_manager() -> bool:
	roles = frappe.get_roles()
	return "Sales Manager" in roles or "System Manager" in roles


def _monday_or_throw(week_start) -> str:
	if frappe.utils.getdate(week_start).weekday() != 0:
		frappe.throw(_("week_start must be a Monday."))
	return str(frappe.utils.getdate(week_start))


@frappe.whitelist()
def get_plan(week_start: str, user: str | None = None):
	"""The plan for one user-week, with a plan-vs-actual rollup per type."""
	week_start = _monday_or_throw(week_start)
	user = user or frappe.session.user
	if user != frappe.session.user and not _is_manager():
		frappe.throw(_("Only managers can view another user's plan."), frappe.PermissionError)

	name = frappe.db.exists("CRM Rep Plan", {"user": user, "week_start": week_start})
	if not name:
		return {"name": None, "user": user, "week_start": week_start, "items": [], "rollup": {}}

	plan = frappe.get_doc("CRM Rep Plan", name)
	items = [{f: item.get(f) for f in ("name", *ITEM_FIELDS)} for item in plan.items]

	rollup: dict[str, dict[str, int]] = {}
	for item in items:
		bucket = rollup.setdefault(item["activity_type"], {"planned": 0, "done": 0, "missed": 0})
		bucket["planned"] += 1
		if item["status"] == "Done":
			bucket["done"] += 1
		elif item["status"] == "Missed":
			bucket["missed"] += 1

	return {
		"name": plan.name,
		"user": user,
		"week_start": week_start,
		"items": items,
		"rollup": rollup,
	}


@frappe.whitelist()
def save_plan(week_start: str, items: list | str):
	"""Create or replace the caller's own plan for the week.

	Matcher-owned fields (status, fulfilment) are preserved for surviving
	items by child-row name; new items start Planned.
	"""
	week_start = _monday_or_throw(week_start)
	if isinstance(items, str):
		items = json.loads(items)

	user = frappe.session.user
	name = frappe.db.exists("CRM Rep Plan", {"user": user, "week_start": week_start})
	plan = (
		frappe.get_doc("CRM Rep Plan", name)
		if name
		else frappe.new_doc("CRM Rep Plan", user=user, week_start=week_start)
	)

	preserved = {item.name: item for item in plan.get("items", [])}
	plan.set("items", [])
	for row in items:
		existing = preserved.get(row.get("name"))
		clean = {
			f: row.get(f)
			for f in (
				"activity_type",
				"planned_date",
				"note",
				"reference_doctype",
				"reference_docname",
				"suggestion",
			)
		}
		if existing:
			clean |= {
				"status": existing.status,
				"fulfilled_by_doctype": existing.fulfilled_by_doctype,
				"fulfilled_by": existing.fulfilled_by,
			}
		plan.append("items", clean)

	plan.save(ignore_permissions=True)

	accepted = [row.get("suggestion") for row in items if row.get("suggestion")]
	for suggestion in set(accepted):
		if frappe.db.get_value("CRM Suggestion", suggestion, "status") == "Open":
			frappe.db.set_value("CRM Suggestion", suggestion, "status", "Accepted")

	return get_plan(week_start)


@frappe.whitelist()
def propose_week(week_start: str):
	"""Draft a week from the caller's open suggestions. Writes nothing."""
	week_start = _monday_or_throw(week_start)
	monday = frappe.utils.getdate(week_start)

	suggestions = frappe.get_list(
		"CRM Suggestion",
		filters={"status": "Open", "user": frappe.session.user},
		fields=[
			"name",
			"title",
			"reference_doctype",
			"reference_docname",
			"suggested_action",
			"score",
		],
		order_by="score desc, creation desc",
		limit_page_length=10,
	)

	drafts = []
	for i, s in enumerate(suggestions):
		planned = monday + timedelta(days=i % 5)  # spread across the workweek
		drafts.append(
			{
				"activity_type": ACTION_TO_ACTIVITY.get(s.suggested_action, "Task"),
				"planned_date": str(planned),
				"note": s.title,
				"reference_doctype": s.reference_doctype,
				"reference_docname": s.reference_docname,
				"suggestion": s.name,
			}
		)
	return drafts
