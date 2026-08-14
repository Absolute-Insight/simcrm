# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Plan-vs-actual fulfilment matching.

``match_items`` is pure: plan-item rows and actual-activity rows in, an
``{item_name: actual}`` assignment out. The scheduler entry ``match_actuals``
feeds it real activity and writes the results back. Plan adherence is
computed from records, never self-reported — an item is Done only when a real
task/call/email/meeting fulfils it, and Missed only once its week has passed.
"""

from __future__ import annotations

from datetime import date, timedelta

import frappe

# item activity_type -> (source doctype, user field, timestamp field)
ACTUAL_SOURCES = {
	"Task": ("CRM Task", "assigned_to", "modified"),
	"Call": ("CRM Call Log", "owner", "creation"),
	"Email": ("Communication", "owner", "creation"),
	"Meeting": ("Event", "owner", "starts_on"),
}

# how many weeks back the matcher still looks at plans
MATCH_HORIZON_WEEKS = 8


def week_of(day: date) -> tuple[date, date]:
	start = day - timedelta(days=day.weekday())
	return start, start + timedelta(days=6)


def match_items(items: list[dict], actuals: list[dict]) -> dict[str, dict]:
	"""Assign actuals to planned items. One actual fulfils at most one item.

	An actual matches an item when the kinds agree, the references agree
	(when the item names one), and the actual falls inside the item's plan
	week. Each actual goes to the closest-dated unfulfilled item.
	"""
	open_items = [i for i in items if i.get("status") == "Planned"]
	assigned: dict[str, dict] = {}

	for actual in sorted(actuals, key=lambda a: a["when"]):
		when = actual["when"].date() if hasattr(actual["when"], "date") else actual["when"]
		candidates = []
		for item in open_items:
			if item["name"] in assigned:
				continue
			if item["activity_type"] != actual["kind"]:
				continue
			if item.get("reference_docname") and (
				item.get("reference_doctype") != actual.get("reference_doctype")
				or item.get("reference_docname") != actual.get("reference_docname")
			):
				continue
			start, end = week_of(item["planned_date"])
			if when < start or when > end:
				continue
			candidates.append(item)
		if candidates:
			best = min(candidates, key=lambda i: abs((i["planned_date"] - when).days))
			assigned[best["name"]] = actual

	return assigned


# --- frappe-facing layer -------------------------------------------------


def _actuals_for(user: str, start: date, end: date) -> list[dict]:
	"""Every activity the user logged inside [start, end], across all kinds."""
	out: list[dict] = []
	end_exclusive = end + timedelta(days=1)
	for kind, (doctype, user_field, when_field) in ACTUAL_SOURCES.items():
		filters = {
			user_field: user,
			when_field: ("between", (str(start), str(end_exclusive))),
		}
		if kind == "Task":
			filters["status"] = "Done"
		if kind == "Email":
			filters["sent_or_received"] = "Sent"
		fields = ["name", f"{when_field} as `when`"]
		has_reference = kind != "Meeting"
		if has_reference:
			ref_name_field = "reference_name" if doctype == "Communication" else "reference_docname"
			fields += ["reference_doctype", f"{ref_name_field} as reference_docname"]
		for row in frappe.get_all(doctype, filters=filters, fields=fields):
			row["doctype"] = doctype
			row["kind"] = kind
			out.append(row)
	return out


def match_actuals() -> int:
	"""Daily scheduler entry. Returns how many items were fulfilled."""
	today = frappe.utils.getdate()
	horizon = today - timedelta(weeks=MATCH_HORIZON_WEEKS)
	plans = frappe.get_all(
		"CRM Rep Plan",
		filters={"week_start": (">=", horizon)},
		fields=["name", "user", "week_start"],
	)

	fulfilled = 0
	for plan in plans:
		items = frappe.get_all(
			"CRM Rep Plan Item",
			filters={"parent": plan.name, "status": "Planned"},
			fields=[
				"name",
				"activity_type",
				"planned_date",
				"reference_doctype",
				"reference_docname",
				"status",
			],
		)
		if not items:
			continue

		start = frappe.utils.getdate(plan.week_start)
		end = start + timedelta(days=6)
		matches = match_items(items, _actuals_for(plan.user, start, end))
		for item_name, actual in matches.items():
			frappe.db.set_value(
				"CRM Rep Plan Item",
				item_name,
				{
					"status": "Done",
					"fulfilled_by_doctype": actual["doctype"],
					"fulfilled_by": actual["name"],
				},
			)
			fulfilled += 1

		if end < today:
			for item in items:
				if item["name"] not in matches:
					frappe.db.set_value("CRM Rep Plan Item", item["name"], "status", "Missed")

	return fulfilled
