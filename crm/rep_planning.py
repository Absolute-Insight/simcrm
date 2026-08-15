# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Plan-vs-actual fulfilment matching.

``match_items`` is pure: plan-item rows and actual-activity rows in, an
``{item_name: actual}`` assignment out. The scheduler entry ``match_actuals``
feeds it real activity and writes the results back. Plan adherence is
computed from records, never self-reported — an item is Done only when a real
task/call/email/meeting fulfils it, and Missed only once its week has passed.

Every run re-derives the whole horizon rather than appending to it: a match is
a claim on a record, so deleting the call or cancelling the meeting behind an
item takes its Done away again, and Missed is a verdict this run reached, not
a state the item is stuck in. The one thing the job never touches is an item a
rep corrected by hand (``manual_override``).
"""

from __future__ import annotations

from datetime import date, timedelta

import frappe
from frappe.query_builder.functions import Coalesce

# item activity_type -> where its fulfilling records live.
#
# ``when_is_activity_time`` says whether ``when_field`` really is the moment the
# activity happened. CRM Task carries no completion timestamp, so Task falls back
# to ``modified``, an edit marker that drifts every time the task is touched
# again; a fulfilment already recorded against a task is therefore never revoked
# on drift alone (see ``_fulfilment_holds``).
ACTUAL_SOURCES = {
	"Task": {
		"doctype": "CRM Task",
		"user_fields": ("assigned_to",),
		"when_field": "modified",
		"when_is_activity_time": False,
		"filters": {"status": "Done"},
	},
	"Call": {
		"doctype": "CRM Call Log",
		# a call logged by telephony is owned by the integration user, not by the
		# rep who made it — the rep is on caller/receiver
		"user_fields": ("caller", "receiver"),
		"when_field": "start_time",
		"when_fallback_field": "creation",
		"when_is_activity_time": True,
		"filters": {"status": "Completed"},
	},
	"Email": {
		"doctype": "Communication",
		"user_fields": ("owner",),
		"when_field": "creation",
		"when_is_activity_time": True,
		# an automated notification, or a phone call logged as a Communication, is
		# not the email the rep planned to write
		"filters": {
			"sent_or_received": "Sent",
			"communication_type": "Communication",
			"communication_medium": "Email",
		},
	},
	"Meeting": {
		"doctype": "Event",
		"user_fields": ("owner",),
		"when_field": "starts_on",
		"when_is_activity_time": True,
		"exclude": {"status": ("Cancelled",)},
	},
}

# Communication names its reference differently to everything else here
REFERENCE_NAME_FIELD = {"Communication": "reference_name"}

# how many weeks back the matcher still looks at plans
MATCH_HORIZON_WEEKS = 8


def week_of(day: date) -> tuple[date, date]:
	start = day - timedelta(days=day.weekday())
	return start, start + timedelta(days=6)


def match_items(items: list[dict], actuals: list[dict]) -> dict[str, dict]:
	"""Assign actuals to planned items. One actual fulfils at most one item.

	An actual matches an item when the kinds agree, the references agree
	(when the item names one), and the actual falls inside the item's plan
	week. Each actual goes to the item that named its reference first and is
	dated closest to it, so a generic "make a call" cannot steal the call a
	specific deal was planned for.
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
			best = min(candidates, key=lambda i: _rank(i, actual, when))
			assigned[best["name"]] = actual

	return assigned


def _rank(item: dict, actual: dict, when: date) -> tuple[int, int, str]:
	"""Sort key for the items an actual could fulfil, best first.

	Reference beats date: an item that named this deal is what the rep meant,
	even when a vaguer item sits a day closer. The name is the final term only
	so that two equally good candidates resolve the same way on every run.
	"""
	on_reference = bool(actual.get("reference_docname")) and (
		item.get("reference_doctype") == actual.get("reference_doctype")
		and item.get("reference_docname") == actual.get("reference_docname")
	)
	return (0 if on_reference else 1, abs((item["planned_date"] - when).days), str(item["name"]))


# --- frappe-facing layer -------------------------------------------------


def _query_source(
	kind: str, user: str, window: tuple[date, date] | None, names: list | None = None
) -> list[dict]:
	"""Activity of one kind belonging to ``user``, as actual rows the matcher reads.

	``window`` restricts to a plan week; pass None to ask only whether given
	records still qualify at all.
	"""
	source = ACTUAL_SOURCES[kind]
	doctype = source["doctype"]
	table = frappe.qb.DocType(doctype)

	when = table[source["when_field"]]
	if source.get("when_fallback_field"):
		# a hand-logged call has no start_time; the moment it was written down is
		# the only timestamp it will ever have
		when = Coalesce(when, table[source["when_fallback_field"]])
	reference_field = REFERENCE_NAME_FIELD.get(doctype, "reference_docname")

	query = frappe.qb.from_(table).select(
		table.name,
		when.as_("happened_at"),
		table.reference_doctype,
		table[reference_field].as_("reference_docname"),
	)

	user_match = None
	for field in source["user_fields"]:
		match = table[field] == user
		user_match = match if user_match is None else user_match | match
	query = query.where(user_match)

	for field, value in source.get("filters", {}).items():
		query = query.where(table[field] == value)
	for field, values in source.get("exclude", {}).items():
		# an unset status is not a cancellation
		query = query.where(table[field].isnull() | table[field].notin(values))

	if names is not None:
		query = query.where(table.name.isin(names))
	if window:
		start, end = window
		query = query.where(when >= start).where(when < end + timedelta(days=1))

	return [
		{
			"doctype": doctype,
			"kind": kind,
			"name": row.name,
			"when": row.happened_at,
			"reference_doctype": row.reference_doctype,
			"reference_docname": row.reference_docname,
		}
		for row in query.run(as_dict=True)
	]


def _actuals_for(user: str, start: date, end: date) -> list[dict]:
	"""Every activity the user logged inside [start, end], across all kinds."""
	out: list[dict] = []
	for kind in ACTUAL_SOURCES:
		out += _query_source(kind, user, (start, end))
	return out


def _fulfilment_holds(item: dict, user: str, start: date, end: date) -> bool:
	"""Does the record recorded against a Done item still fulfil it?

	Deleting the call, reopening the task or cancelling the meeting takes the
	fulfilment with it — Done is a statement about a record, not a flag.
	"""
	source = ACTUAL_SOURCES.get(item["activity_type"])
	if not source or not item["fulfilled_by"] or item["fulfilled_by_doctype"] != source["doctype"]:
		return False
	window = (start, end) if source["when_is_activity_time"] else None
	return bool(_query_source(item["activity_type"], user, window, names=[item["fulfilled_by"]]))


def _claimed_actuals(horizon: date) -> dict[tuple[str, str], str]:
	"""(doctype, name) -> the plan item already holding that record.

	One record fulfils one item, ever. Without this a task completed in one week
	and edited in the next would be counted twice — once where it was planned,
	once where it was touched.
	"""
	item = frappe.qb.DocType("CRM Rep Plan Item")
	plan = frappe.qb.DocType("CRM Rep Plan")
	rows = (
		frappe.qb.from_(item)
		.join(plan)
		.on(item.parent == plan.name)
		.select(item.name, item.fulfilled_by_doctype, item.fulfilled_by)
		.where(plan.week_start >= horizon)
		.where(item.fulfilled_by.isnotnull())
		.where(item.fulfilled_by != "")
		.run(as_dict=True)
	)
	return {(row.fulfilled_by_doctype, str(row.fulfilled_by)): row.name for row in rows}


def _match_plan(plan: dict, today: date, claimed: dict[tuple[str, str], str]) -> int:
	"""Re-derive one plan's fulfilment. Returns how many items newly went Done."""
	items = frappe.get_all(
		"CRM Rep Plan Item",
		filters={"parent": plan.name, "parenttype": "CRM Rep Plan"},
		fields=[
			"name",
			"activity_type",
			"planned_date",
			"reference_doctype",
			"reference_docname",
			"status",
			"fulfilled_by_doctype",
			"fulfilled_by",
			"manual_override",
		],
		order_by="idx asc",
	)
	# a rep who corrected an item by hand owns it; the job has no opinion left
	items = [row for row in items if not row.manual_override]
	if not items:
		return 0

	start = frappe.utils.getdate(plan.week_start)
	end = start + timedelta(days=6)
	before = {row.name: (row.status, row.fulfilled_by_doctype, row.fulfilled_by) for row in items}

	for row in items:
		if row.status == "Done" and _fulfilment_holds(row, plan.user, start, end):
			continue
		if claimed.get((row.fulfilled_by_doctype, str(row.fulfilled_by))) == row.name:
			del claimed[(row.fulfilled_by_doctype, str(row.fulfilled_by))]
		row.update({"status": "Planned", "fulfilled_by_doctype": None, "fulfilled_by": None})

	actuals = [
		actual
		for actual in _actuals_for(plan.user, start, end)
		if (actual["doctype"], str(actual["name"])) not in claimed
	]
	by_name = {row.name: row for row in items}
	for item_name, actual in match_items(items, actuals).items():
		by_name[item_name].update(
			{
				"status": "Done",
				"fulfilled_by_doctype": actual["doctype"],
				"fulfilled_by": str(actual["name"]),
			}
		)
		claimed[(actual["doctype"], str(actual["name"]))] = item_name

	if end < today:
		for row in items:
			if row.status == "Planned":
				row.status = "Missed"

	fulfilled = 0
	for row in items:
		after = (row.status, row.fulfilled_by_doctype, row.fulfilled_by)
		if after == before[row.name]:
			continue
		frappe.db.set_value(
			"CRM Rep Plan Item",
			row.name,
			{
				"status": row.status,
				"fulfilled_by_doctype": row.fulfilled_by_doctype,
				"fulfilled_by": row.fulfilled_by,
			},
		)
		if row.status == "Done":
			fulfilled += 1
	return fulfilled


def _close_stranded_items(horizon: date) -> None:
	"""Weeks older than the horizon stop being open questions.

	Adherence counts every item whose date has passed, so one left Planned in a
	week the matcher no longer visits would dock its rep for good, and planned
	would never reconcile with done + missed.
	"""
	stale = frappe.get_all("CRM Rep Plan", filters={"week_start": ("<", horizon)}, pluck="name")
	if not stale:
		return
	frappe.db.set_value(
		"CRM Rep Plan Item",
		{
			"parenttype": "CRM Rep Plan",
			"parent": ("in", stale),
			"status": "Planned",
			"manual_override": 0,
		},
		"status",
		"Missed",
		update_modified=False,
	)


def match_actuals() -> int:
	"""Daily scheduler entry. Returns how many items were newly fulfilled."""
	today = frappe.utils.getdate()
	horizon = today - timedelta(weeks=MATCH_HORIZON_WEEKS)
	plans = frappe.get_all(
		"CRM Rep Plan",
		filters={"week_start": (">=", horizon)},
		fields=["name", "user", "week_start"],
		# oldest first, so the week an activity was planned for claims it before a
		# later week that merely happens to overlap
		order_by="week_start asc, name asc",
	)

	claimed = _claimed_actuals(horizon)
	fulfilled = 0
	for plan in plans:
		savepoint = f"match_plan_{plan.name}"
		frappe.db.savepoint(savepoint)
		try:
			fulfilled += _match_plan(plan, today, claimed)
		except Exception:
			# a deleted user or a dangling link on one rep's week must not discard
			# every rep the job already matched
			frappe.db.rollback(save_point=savepoint)
			frappe.log_error(title=f"match_actuals failed for plan {plan.name}")
		else:
			# tests run inside one transaction that is rolled back afterwards
			if not frappe.in_test:
				frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	_close_stranded_items(horizon)
	return fulfilled
