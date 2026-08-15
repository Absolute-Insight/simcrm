# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Rep-plan endpoints.

Visibility follows the sales hierarchy that scopes leads and deals; everyone
edits only their own week. ``propose_week`` returns drafts only — the rep
reviews and saves explicitly, which is the Phase 8 write-gate rule applied to
planning: agent-proposed items become records only after a human confirms them.

Fulfilment is the daily matcher's to decide (``crm.rep_planning``), with one
exception: ``mark_fulfilled``/``mark_missed`` let a rep correct an item the
records cannot speak for, and flag it so the job leaves it alone.
"""

from __future__ import annotations

import json
from datetime import timedelta

import frappe
from frappe import _

from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users
from crm.rep_planning import ACTUAL_SOURCES, MATCH_HORIZON_WEEKS

ITEM_FIELDS = (
	"activity_type",
	"planned_date",
	"note",
	"reference_doctype",
	"reference_docname",
	"status",
	"fulfilled_by_doctype",
	"fulfilled_by",
	"manual_override",
	"suggestion",
)

# the fields a client may set; everything else on a row belongs to the matcher
EDITABLE_ITEM_FIELDS = (
	"activity_type",
	"planned_date",
	"note",
	"reference_doctype",
	"reference_docname",
	"suggestion",
)

# a plan item points at the record it is about, and only these are plannable
REFERENCE_DOCTYPES = ("CRM Deal", "CRM Lead")

FULFILMENT_DOCTYPES = tuple(source["doctype"] for source in ACTUAL_SOURCES.values())

ACTION_TO_ACTIVITY = {
	"create_task": "Task",
	"schedule_call": "Call",
	"send_reply": "Email",
	"update_field": "Task",
}


def _can_view(target_user: str) -> bool:
	if target_user == frappe.session.user:
		return True
	users = visible_users()
	return users is None or target_user in users


def _monday_or_throw(week_start) -> str:
	if frappe.utils.getdate(week_start).weekday() != 0:
		frappe.throw(_("week_start must be a Monday."))
	return str(frappe.utils.getdate(week_start))


@frappe.whitelist()
def get_visible_reps() -> list[str]:
	"""The users whose plans the caller may open, for the planner's rep picker.

	Listing every CRM user instead would offer a manager rows they cannot read
	and a rep rows that are none of their business.
	"""
	users = visible_users()
	if users is None:
		users = frappe.get_all(
			"User",
			filters=[
				["User", "enabled", "=", 1],
				["Has Role", "role", "in", ("Sales User", "Sales Manager")],
			],
			pluck="name",
			distinct=True,
		)
	return sorted({*users, frappe.session.user})


@frappe.whitelist()
def get_plan(week_start: str, user: str | None = None):
	"""The plan for one user-week, with a plan-vs-actual rollup per type."""
	week_start = _monday_or_throw(week_start)
	user = user or frappe.session.user
	if not _can_view(user):
		frappe.throw(_("You are not allowed to view this user's plan."), frappe.PermissionError)

	name = frappe.db.exists("CRM Rep Plan", {"user": user, "week_start": week_start})
	if not name:
		return {
			"name": None,
			"user": user,
			"week_start": week_start,
			"modified": None,
			"items": [],
			"rollup": {},
		}

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
		"modified": plan.modified,
		"items": items,
		"rollup": rollup,
	}


def _stage_items(plan, items: list[dict]) -> set[str]:
	"""Rebuild the plan's rows from the client's, keeping what the matcher decided.

	Returns the suggestions the plan claimed before this save and no longer does.
	"""
	preserved = {str(row.name): row for row in plan.get("items", [])}
	# a row already Done was acted on; only the ones dropped before anything
	# happened release their suggestion back to the inbox
	dropped = {row.suggestion for row in plan.get("items", []) if row.suggestion and row.status != "Done"}

	plan.set("items", [])
	for row in items:
		reference_doctype = row.get("reference_doctype")
		if reference_doctype and reference_doctype not in REFERENCE_DOCTYPES:
			frappe.throw(_("Cannot plan against {0}.").format(reference_doctype))

		clean = {f: row.get(f) for f in EDITABLE_ITEM_FIELDS}
		existing = preserved.get(str(row.get("name") or ""))
		if existing:
			# rescheduling a row is not the same as replacing it: it keeps its name,
			# so links to it survive, and it keeps whatever the matcher already found
			clean |= {
				"name": existing.name,
				"status": existing.status,
				"fulfilled_by_doctype": existing.fulfilled_by_doctype,
				"fulfilled_by": existing.fulfilled_by,
				"manual_override": existing.manual_override,
			}
		plan.append("items", clean)

	return dropped - {row.get("suggestion") for row in items if row.get("suggestion")}


@frappe.whitelist()
def save_plan(week_start: str, items: list | str, modified: str | None = None):
	"""Create or replace the caller's own plan for the week.

	Matcher-owned fields (status, fulfilment) are preserved for surviving
	items by child-row name; new items start Planned. Pass the ``modified``
	that came back from :func:`get_plan` to be told about a newer version
	instead of overwriting it.
	"""
	week_start = _monday_or_throw(week_start)
	if isinstance(items, str):
		items = json.loads(items)

	horizon = frappe.utils.getdate() - timedelta(weeks=MATCH_HORIZON_WEEKS)
	if frappe.utils.getdate(week_start) < horizon:
		# the matcher stops looking this far back, so anything saved here could
		# only ever be Planned
		frappe.throw(_("Plans older than {0} weeks can no longer be edited.").format(MATCH_HORIZON_WEEKS))

	user = frappe.session.user
	if modified:
		current = frappe.db.get_value("CRM Rep Plan", {"user": user, "week_start": week_start}, "modified")
		if not current or frappe.utils.get_datetime(current) != frappe.utils.get_datetime(modified):
			frappe.throw(
				_("This plan changed since you opened it. Reload before saving."),
				frappe.TimestampMismatchError,
			)

	for attempt in range(2):
		plan = _plan_for(user, week_start)
		released = _stage_items(plan, items)
		frappe.db.savepoint("save_plan")
		try:
			plan.save(ignore_permissions=True)
			break
		except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
			# a concurrent first save of the same week got past the exists() check;
			# the unique index settles it and the loser re-reads the winner's plan
			frappe.db.rollback(save_point="save_plan")
			if attempt:
				raise

	# Only the caller's own open suggestions may be closed by saving a plan — the
	# item rows arrive from the client, so a name in there is a request, not proof
	# of ownership.
	accepted = {row.get("suggestion") for row in items if row.get("suggestion")}
	_set_suggestion_status(accepted, user, "Open", "Accepted")
	# and a suggestion whose item was dropped again was never acted on
	_set_suggestion_status(released, user, "Accepted", "Open")

	return get_plan(week_start)


def _plan_for(user: str, week_start: str):
	name = frappe.db.exists("CRM Rep Plan", {"user": user, "week_start": week_start})
	if name:
		return frappe.get_doc("CRM Rep Plan", name)
	return frappe.new_doc("CRM Rep Plan", user=user, week_start=week_start)


def _set_suggestion_status(names: set[str], user: str, expected: str, status: str) -> None:
	for name in names:
		owner, current = frappe.db.get_value("CRM Suggestion", name, ["user", "status"]) or (None, None)
		if current == expected and owner == user:
			frappe.db.set_value("CRM Suggestion", name, "status", status)


def _own_plan_of(item: str):
	"""The plan an item belongs to, refused unless it is the caller's own."""
	row = frappe.db.get_value("CRM Rep Plan Item", item, ["parent", "parenttype"], as_dict=True)
	if not row or row.parenttype != "CRM Rep Plan":
		frappe.throw(_("Plan item {0} not found.").format(item), frappe.DoesNotExistError)

	plan = frappe.db.get_value("CRM Rep Plan", row.parent, ["user", "week_start"], as_dict=True)
	if plan.user != frappe.session.user:
		frappe.throw(_("Only a plan's own user can change its items."), frappe.PermissionError)
	return plan


@frappe.whitelist()
def mark_fulfilled(item: str, fulfilled_by_doctype: str | None = None, fulfilled_by: str | None = None):
	"""Mark one of the caller's own items done by hand, optionally naming the record.

	The matcher reads records and some work leaves none — a call from a personal
	phone, a meeting nobody put in a calendar. ``manual_override`` is the rep's
	word standing in for the missing record, and the daily job never overwrites
	it, in either direction.
	"""
	plan = _own_plan_of(item)
	if fulfilled_by_doctype and fulfilled_by_doctype not in FULFILMENT_DOCTYPES:
		frappe.throw(_("{0} cannot fulfil a plan item.").format(fulfilled_by_doctype))
	if fulfilled_by and not fulfilled_by_doctype:
		frappe.throw(_("Name the document type that fulfilled this item."))

	frappe.db.set_value(
		"CRM Rep Plan Item",
		item,
		{
			"status": "Done",
			"manual_override": 1,
			"fulfilled_by_doctype": fulfilled_by_doctype,
			"fulfilled_by": fulfilled_by,
		},
	)
	return get_plan(str(plan.week_start), plan.user)


@frappe.whitelist()
def mark_missed(item: str):
	"""Write one of the caller's own items off by hand, before its week is over."""
	plan = _own_plan_of(item)
	frappe.db.set_value(
		"CRM Rep Plan Item",
		item,
		{
			"status": "Missed",
			"manual_override": 1,
			"fulfilled_by_doctype": None,
			"fulfilled_by": None,
		},
	)
	return get_plan(str(plan.week_start), plan.user)


@frappe.whitelist()
def clear_override(item: str):
	"""Hand an item the rep had corrected back to the matcher."""
	plan = _own_plan_of(item)
	frappe.db.set_value(
		"CRM Rep Plan Item",
		item,
		{
			"status": "Planned",
			"manual_override": 0,
			"fulfilled_by_doctype": None,
			"fulfilled_by": None,
		},
	)
	return get_plan(str(plan.week_start), plan.user)


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
			"action_payload",
			"reference_doctype",
			"reference_docname",
			"suggested_action",
			"score",
		],
		order_by="score desc, creation desc",
		limit_page_length=10,
	)

	days = _spread_days(monday)
	drafts = []
	for i, s in enumerate(suggestions):
		drafts.append(
			{
				"activity_type": ACTION_TO_ACTIVITY.get(s.suggested_action, "Task"),
				"planned_date": str(days[i % len(days)]),
				"note": _draft_note(s),
				"reference_doctype": s.reference_doctype,
				"reference_docname": s.reference_docname,
				"suggestion": s.name,
			}
		)
	return drafts


def _draft_note(suggestion) -> str:
	"""The activity to do, not the reason it is being suggested.

	A suggestion's title addresses the rep ("Overdue plan item: Call Acme"),
	while its payload title is the thing itself ("Call Acme"). Only the payload
	makes sense written on a planner card -- and the ``stale_plan`` signal reads
	plan notes back, so titling the draft from the title nests the prefix a
	little deeper every week it is missed.
	"""
	try:
		payload = json.loads(suggestion.action_payload or "{}")
	except (ValueError, TypeError):
		payload = {}
	title = payload.get("title") if isinstance(payload, dict) else None
	return (title or suggestion.title or "").strip()


def _spread_days(monday):
	"""The days of that week a draft may still land on.

	Proposing a week on Wednesday used to put its first drafts on Monday, i.e.
	overdue the moment they were saved. What is left of the workweek comes first,
	then the weekend; a week already wholly past is a deliberate backfill and
	keeps its Mon-Fri.
	"""
	first = max(monday, frappe.utils.getdate())
	week = [monday + timedelta(days=i) for i in range(7)]
	remaining = [day for day in week[:5] if day >= first]
	if remaining:
		return remaining
	return [day for day in week[5:] if day >= first] or week[:5]
