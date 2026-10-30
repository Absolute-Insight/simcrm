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
from datetime import datetime, time, timedelta

import frappe
from frappe import _

from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users
from crm.rep_planning import (
	ACTIVITY_TYPES,
	ACTUAL_SOURCES,
	EVENT_KINDS,
	KIND_BY_DOCTYPE,
	MATCH_HORIZON_WEEKS,
	_claimed_actuals,
	_query_source,
	week_of,
)
from crm.utils import sales_user_only

ITEM_FIELDS = (
	"activity_type",
	"planned_date",
	"note",
	"reference_doctype",
	"reference_docname",
	"organization",
	"status",
	"outcome",
	"fulfilled_by_doctype",
	"fulfilled_by",
	"manual_override",
	"suggestion",
)

# One request may replace the whole week; this is far above any plan a person
# writes by hand and keeps a client from growing the child table without bound.
MAX_PLAN_ITEMS = 200

# the fields a client may set; everything else on a row belongs to the matcher
EDITABLE_ITEM_FIELDS = (
	"activity_type",
	"planned_date",
	"note",
	"reference_doctype",
	"reference_docname",
	"organization",
	"suggestion",
)

# CRM Rep Plan Item.note is a Data field; anything longer goes in the outcome
NOTE_LIMIT = 140

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
@sales_user_only
def get_visible_reps() -> list[str]:
	"""The users whose plans the caller may open, for the planner's rep picker.

	Listing every CRM user instead would offer a manager rows they cannot read
	and a rep rows that are none of their business.
	"""
	users = visible_users()
	if users is None:
		users = planning_reps()
	return sorted({*users, frappe.session.user})


def planning_reps() -> list[str]:
	"""The sales users there is planning to show: every enabled one, and a
	disabled one whose plans are still recent.

	Disabled is not always gone. MBP's reps were disabled so they could not log
	in before go-live while their imported history filled the planner, and an
	enabled-only list emptied the managers' team week and left the reps out of
	Settings -> Visit Targets. A rep who has left drops out once their last plan
	is older than the match horizon, the window in which a plan still changes.
	"""
	users = frappe.get_all(
		"User",
		filters=[["Has Role", "role", "in", ("Sales User", "Sales Manager")]],
		fields=["name", "enabled"],
		distinct=True,
	)
	enabled = {u.name for u in users if u.enabled}
	disabled = [u.name for u in users if not u.enabled]
	if disabled:
		horizon = frappe.utils.getdate() - timedelta(weeks=MATCH_HORIZON_WEEKS)
		enabled.update(
			frappe.get_all(
				"CRM Rep Plan",
				filters={"user": ("in", disabled), "week_start": (">=", horizon)},
				pluck="user",
				distinct=True,
			)
		)
	return sorted(enabled)


@frappe.whitelist()
@sales_user_only
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

	return {
		"name": plan.name,
		"user": user,
		"week_start": week_start,
		"modified": plan.modified,
		"items": items,
		"rollup": _rollup(items),
	}


def _rollup(items: list[dict]) -> dict[str, dict[str, int]]:
	"""Per activity type: every row counts as planned, and Done / Missed /
	Cancelled also count in their own bucket. ``rollupItems`` in
	frontend/src/utils/planner.js is the same definition."""
	rollup: dict[str, dict[str, int]] = {}
	for item in items:
		bucket = rollup.setdefault(
			item["activity_type"], {"planned": 0, "done": 0, "missed": 0, "cancelled": 0}
		)
		bucket["planned"] += 1
		if item["status"] == "Done":
			bucket["done"] += 1
		elif item["status"] == "Missed":
			bucket["missed"] += 1
		elif item["status"] == "Cancelled":
			bucket["cancelled"] += 1
	return rollup


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
		# The client resends the reference it loaded the week with, and a deal or
		# lead can now be deleted out from under a plan item (clear_plan_item_references
		# nulls the stored row without touching the plan's `modified`, so the
		# optimistic-lock check cannot see it). Re-adopting a name that is gone
		# would fail the whole save on a link-validation error the rep can do
		# nothing about, losing the rest of their week's edits.
		if clean.get("reference_doctype") and clean.get("reference_docname"):
			# ...and a record the rep may not read is not theirs to plan against: the
			# item's reference reaches the visit event closing it, and through that
			# event client_reliability would show the deal's organization
			if not _can_reference(clean["reference_doctype"], clean["reference_docname"]):
				clean["reference_doctype"] = None
				clean["reference_docname"] = None
		# same reasoning for the customer: a merged or deleted organization must
		# not fail the whole week's save
		if clean.get("organization") and not frappe.db.exists("CRM Organization", clean["organization"]):
			clean["organization"] = None
		existing = preserved.get(str(row.get("name") or ""))
		if existing:
			# rescheduling a row is not the same as replacing it: it keeps its name,
			# so links to it survive, and it keeps whatever the matcher already found
			clean |= {
				"name": existing.name,
				"status": existing.status,
				"outcome": existing.outcome,
				"fulfilled_by_doctype": existing.fulfilled_by_doctype,
				"fulfilled_by": existing.fulfilled_by,
				"manual_override": existing.manual_override,
			}
		plan.append("items", clean)

	return dropped - {row.get("suggestion") for row in items if row.get("suggestion")}


def _can_reference(doctype: str, name: str) -> bool:
	return bool(frappe.db.exists(doctype, name)) and bool(
		frappe.has_permission(doctype, "read", doc=name, user=frappe.session.user)
	)


def _items_or_throw(items) -> list[dict]:
	"""The wire's ``items`` as a bounded list of dicts, or a clean error.

	Anything else used to fall through to ``plan.append`` and 500; a list with
	no ceiling was a way to write an unbounded child table in one request.
	"""
	if isinstance(items, str):
		try:
			items = json.loads(items)
		except ValueError:
			frappe.throw(_("Plan items must be a list."), frappe.ValidationError)
	if not isinstance(items, list) or not all(isinstance(row, dict) for row in items):
		frappe.throw(_("Plan items must be a list."), frappe.ValidationError)
	if len(items) > MAX_PLAN_ITEMS:
		frappe.throw(
			_("A week's plan can hold at most {0} items.").format(MAX_PLAN_ITEMS), frappe.ValidationError
		)
	return items


@frappe.whitelist()
@sales_user_only
def save_plan(week_start: str, items: list | str, modified: str | None = None):
	"""Create or replace the caller's own plan for the week.

	Matcher-owned fields (status, fulfilment) are preserved for surviving
	items by child-row name; new items start Planned. Pass the ``modified``
	that came back from :func:`get_plan` to be told about a newer version
	instead of overwriting it.
	"""
	week_start = _monday_or_throw(week_start)
	items = _items_or_throw(items)

	horizon = frappe.utils.getdate() - timedelta(weeks=MATCH_HORIZON_WEEKS)
	if frappe.utils.getdate(week_start) < horizon:
		# the matcher stops looking this far back, so anything saved here could
		# only ever be Planned
		frappe.throw(_("Plans older than {0} weeks can no longer be edited.").format(MATCH_HORIZON_WEEKS))

	user = frappe.session.user
	if modified is not None:
		# What the caller saw when they loaded the week: a timestamp, or "" for
		# "there was no plan". Either is checked against what is there now, so a
		# tab opened on an empty week cannot replace a plan another tab or device
		# created meanwhile. None means the caller makes no claim (a server-side
		# caller, or an old client) and the save goes through unchecked.
		current = frappe.db.get_value("CRM Rep Plan", {"user": user, "week_start": week_start}, "modified")
		if modified == "":
			changed = bool(current)
		else:
			changed = not current or frappe.utils.get_datetime(current) != frappe.utils.get_datetime(modified)
		if changed:
			frappe.throw(
				_("This plan changed since you opened it. Reload before saving."),
				frappe.TimestampMismatchError,
			)

	for attempt in range(2):
		plan = _plan_for(user, week_start)
		_refuse_the_past(plan, items)
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


def past_days_locked() -> bool:
	"""FCRM Settings -> "Plan only for today or later": a plan is a future event."""
	return bool(frappe.db.get_single_value("FCRM Settings", "lock_past_plans"))


def _refuse_the_past(plan, items: list[dict]) -> None:
	"""With past days locked, nothing is planned, changed or removed before today.

	MBP's managers asked for it: a plan written after the day is not a plan. A
	row dated before today is frozen as it stands -- its type, customer, note
	and day -- because a past Done call edited into a Done visit, or a missed
	visit moved off its day, is the same backdating by another door. What it
	became is still the rep's to say: complete_item and cancel_item do not go
	through here, and cancelling, not deleting, is how a past row is withdrawn.
	A row the client sends back unchanged passes, so saving the rest of the week
	still works.
	"""
	if not past_days_locked():
		return
	today = frappe.utils.getdate()

	def value(field, raw):
		if field == "planned_date":
			return frappe.utils.getdate(raw) if raw else None
		return frappe.utils.cstr(raw) or None

	def snapshot(row):
		return {field: value(field, row.get(field)) for field in EDITABLE_ITEM_FIELDS}

	past = {
		str(row.name): snapshot(row)
		for row in plan.get("items", [])
		if row.planned_date and frappe.utils.getdate(row.planned_date) < today
	}
	for row in items:
		before = past.get(str(row.get("name") or ""))
		if before is not None:
			if snapshot(row) != before:
				frappe.throw(
					_(
						"An activity on {0} has passed and cannot be changed. Log its outcome or cancel it."
					).format(frappe.utils.formatdate(before["planned_date"])),
					frappe.ValidationError,
				)
			continue
		day = value("planned_date", row.get("planned_date"))
		if day and day < today:
			frappe.throw(
				_("{0} has passed. Activities are planned for today or later.").format(
					frappe.utils.formatdate(day)
				),
				frappe.ValidationError,
			)
	kept = {str(row.get("name")) for row in items if row.get("name")}
	for name, before in past.items():
		if name not in kept:
			frappe.throw(
				_("An activity on {0} has passed and cannot be removed. Cancel it instead.").format(
					frappe.utils.formatdate(before["planned_date"])
				),
				frappe.ValidationError,
			)


def _plan_for(user: str, week_start: str):
	name = frappe.db.exists("CRM Rep Plan", {"user": user, "week_start": week_start})
	if name:
		return frappe.get_doc("CRM Rep Plan", name)
	return frappe.new_doc("CRM Rep Plan", user=user, week_start=week_start)


def _set_suggestion_status(names: set[str], user: str, expected: str, status: str) -> None:
	if not names:
		return
	# one read filtered on owner and current status, one write for what matched
	matched = frappe.get_all(
		"CRM Suggestion",
		filters={"name": ("in", list(names)), "user": user, "status": expected},
		pluck="name",
	)
	if matched:
		frappe.db.set_value("CRM Suggestion", {"name": ("in", matched)}, "status", status)


def _own_plan_of(item: str):
	"""The plan an item belongs to, refused unless it is the caller's own."""
	row = frappe.db.get_value("CRM Rep Plan Item", item, ["parent", "parenttype"], as_dict=True)
	if not row or row.parenttype != "CRM Rep Plan":
		frappe.throw(_("Plan item {0} not found.").format(item), frappe.DoesNotExistError)

	plan = frappe.db.get_value("CRM Rep Plan", row.parent, ["user", "week_start"], as_dict=True)
	if plan.user != frappe.session.user:
		frappe.throw(_("Only a plan's own user can change its items."), frappe.PermissionError)
	return plan


def _refuse_a_second_claim(item: str, fulfilled_by_doctype: str, fulfilled_by: str):
	"""One record fulfils one item, ever.

	That is the matcher's own rule (``_claimed_actuals``), and a hand override was
	the one way round it: naming the same call on two items made both Done and
	counted one call twice towards adherence.
	"""
	horizon = frappe.utils.getdate() - timedelta(weeks=MATCH_HORIZON_WEEKS)
	holder = _claimed_actuals(horizon).get((fulfilled_by_doctype, str(fulfilled_by)))
	if holder and holder != item:
		frappe.throw(
			_("{0} {1} is already what fulfils another planned item.").format(
				fulfilled_by_doctype, fulfilled_by
			)
		)


def _refuse_a_record_from_another_week(kind: str, actual: dict, plan, fulfilled_by_doctype, fulfilled_by):
	"""A record fulfils an item only inside the week that item was planned for --
	the same window :func:`match_items` matches in, so an override cannot claim
	what the job would never have assigned.

	Skipped for the kinds whose timestamp is not the activity's moment: CRM Task
	carries no completion time and falls back to ``modified``, which moves every
	time the task is touched, so a task genuinely done in the planned week can
	read as this week by the time the rep corrects the item.
	"""
	if not ACTUAL_SOURCES[kind]["when_is_activity_time"]:
		return
	when = actual.get("when")
	if not when:
		return
	when = when.date() if hasattr(when, "date") else frappe.utils.getdate(when)
	start, end = week_of(frappe.utils.getdate(plan.week_start))
	if when < start or when > end:
		frappe.throw(
			_("{0} {1} did not happen in the week of {2}.").format(fulfilled_by_doctype, fulfilled_by, start)
		)


@frappe.whitelist()
@sales_user_only
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
	if fulfilled_by:
		# The claim is a request, not proof: ``_claimed_actuals`` indexes claims
		# across every plan in the horizon, so an unverified name would exclude
		# the real record from its own rep's matching and dock their adherence.
		# The matcher's own definition of "this rep's completed work" decides --
		# existence, the kind's status filters, and ownership in one query.
		# Event backs two kinds (Meeting, Visit) with different filters, so the
		# item's own kind decides which set of filters the record must satisfy;
		# the doctype-keyed fallback keeps cross-kind fulfilment as it was.
		item_kind = frappe.db.get_value("CRM Rep Plan Item", item, "activity_type")
		if ACTUAL_SOURCES.get(item_kind, {}).get("doctype") == fulfilled_by_doctype:
			kind = item_kind
		else:
			kind = KIND_BY_DOCTYPE[fulfilled_by_doctype]
		rows = _query_source(kind, frappe.session.user, None, names=[fulfilled_by])
		if not rows:
			frappe.throw(
				_("{0} {1} is not a completed activity of yours.").format(fulfilled_by_doctype, fulfilled_by)
			)
		_refuse_a_second_claim(item, fulfilled_by_doctype, fulfilled_by)
		_refuse_a_record_from_another_week(kind, rows[0], plan, fulfilled_by_doctype, fulfilled_by)

	_drop_cancellation(item, plan.user)
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
@sales_user_only
def mark_missed(item: str):
	"""Write one of the caller's own items off by hand, before its week is over."""
	plan = _own_plan_of(item)
	_drop_cancellation(item, plan.user)
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
@sales_user_only
def clear_override(item: str):
	"""Hand an item the rep had corrected back to the matcher."""
	plan = _own_plan_of(item)
	_drop_cancellation(item, plan.user)
	frappe.db.set_value(
		"CRM Rep Plan Item",
		item,
		{
			"status": "Planned",
			"manual_override": 0,
			"outcome": None,
			"fulfilled_by_doctype": None,
			"fulfilled_by": None,
		},
	)
	return get_plan(str(plan.week_start), plan.user)


def _item_row(item: str):
	return frappe.db.get_value(
		"CRM Rep Plan Item",
		item,
		[
			"name",
			"activity_type",
			"planned_date",
			"note",
			"organization",
			"reference_doctype",
			"reference_docname",
			"status",
			"fulfilled_by_doctype",
			"fulfilled_by",
		],
		as_dict=True,
	)


def _drop_cancellation(item: str, user: str) -> None:
	"""Undo the calendar side of :func:`cancel_item` when the rep changes their mind.

	A cancelled visit is recorded as a Cancelled Visit event so the calendar,
	client reliability and the cancellation counts see it. Once the item is no
	longer Cancelled that event would keep counting a cancellation that did not
	happen, so it goes with the status. Only an event this item holds and that
	is itself Cancelled is touched -- a completed visit is a record of real work
	and stays.

	The delete bypasses permissions, so what the item names is not taken on
	trust: only a Cancelled Visit event of the plan's own rep -- what cancel_item
	writes -- is deleted, whatever else an item may have come to point at.
	"""
	row = _item_row(item)
	if not row or row.status != "Cancelled" or row.fulfilled_by_doctype != "Event" or not row.fulfilled_by:
		return
	event = frappe.db.get_value(
		"Event", row.fulfilled_by, ["status", "owner", "event_category"], as_dict=True
	)
	if event and event.status == "Cancelled" and event.owner == user and event.event_category == "Visit":
		frappe.delete_doc("Event", row.fulfilled_by, ignore_permissions=True, force=True)


def _required_text(value: str | None, message: str) -> str:
	text = (value or "").strip()
	if not text:
		frappe.throw(message, frappe.ValidationError)
	return text


def _when_in_week(when: str | None, planned_date, week_start) -> datetime:
	"""The moment an activity happened, defaulting to its planned day.

	Same window the matcher uses -- the item's own week -- and never in the
	future, for the reason ``log_unplanned_visit`` gives.
	"""
	now = frappe.utils.now_datetime()
	if when:
		moment = frappe.utils.get_datetime(when)
	else:
		day = frappe.utils.getdate(planned_date)
		# the planned day at the current time of day, or now if that is still ahead
		moment = min(datetime.combine(day, now.time().replace(microsecond=0)), now)
	if moment > now:
		frappe.throw(_("An activity cannot be completed before it happens."), frappe.ValidationError)
	start, end = week_of(frappe.utils.getdate(week_start))
	if not start <= moment.date() <= end:
		frappe.throw(
			_("That is outside the week of {0}. Move the activity to that week first.").format(start),
			frappe.ValidationError,
		)
	return moment


def _visit_event(
	kind: str,
	organization: str | None,
	when,
	status: str,
	description: str,
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
) -> str:
	"""The calendar Event behind a visit, delivery or unplanned meeting.

	Category Visit is what the matcher, the calendar and client reliability all
	read; the subject keeps the kind so a delivery does not look like a sales
	call on the calendar. Private, and owned by the session user -- the rep.
	"""
	label = organization or _(kind)
	event = frappe.get_doc(
		{
			"doctype": "Event",
			"subject": f"{_(kind)}: {label}",
			"starts_on": when,
			"ends_on": when + timedelta(hours=1),
			"event_type": "Private",
			"event_category": "Visit",
			"status": status,
			"description": frappe.utils.escape_html(description).replace("\n", "<br>"),
			"send_reminder": 0,
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
			"event_participants": (
				[{"reference_doctype": "CRM Organization", "reference_docname": organization}]
				if organization
				else []
			),
		}
	).insert(ignore_permissions=True)
	return event.name


@frappe.whitelist()
@sales_user_only
def complete_item(item: str, outcome: str, when: str | None = None):
	"""Close one of the caller's own planned items as done, saying what happened.

	The old rep app's habit, and the one MBP's managers asked to keep: nothing is
	ticked off without a note. A visit, delivery or unplanned meeting also gets
	its Completed Visit event against the customer, so the calendar and the
	customer reports see it exactly as they see a visit logged on the day; a
	call, email or admin item is the rep's word, as in :func:`mark_fulfilled`.
	"""
	plan = _own_plan_of(item)
	outcome = _required_text(outcome, _("Say what happened."))
	row = _item_row(item)
	if row.status == "Done":
		frappe.throw(_("This activity is already done."), frappe.ValidationError)
	_refuse_outside_horizon(plan.week_start)
	moment = _when_in_week(when, row.planned_date, plan.week_start)

	_drop_cancellation(item, plan.user)
	event = None
	if row.activity_type in EVENT_KINDS:
		event = _visit_event(
			row.activity_type,
			row.organization,
			moment,
			"Completed",
			outcome,
			row.reference_doctype,
			row.reference_docname,
		)
	frappe.db.set_value(
		"CRM Rep Plan Item",
		item,
		{
			"status": "Done",
			"manual_override": 1,
			"outcome": outcome,
			"fulfilled_by_doctype": "Event" if event else None,
			"fulfilled_by": event,
		},
	)
	return get_plan(str(plan.week_start), plan.user)


@frappe.whitelist()
@sales_user_only
def cancel_item(item: str, reason: str):
	"""Cancel one of the caller's own planned items, saying why.

	Cancelled is neither done nor missed: the customer moved the visit, the
	plant was shut. Adherence leaves it out of what was due, and a visit-type
	item also leaves a Cancelled Visit event against the customer, which is what
	client reliability counts and what the old rep app's history carries.
	"""
	plan = _own_plan_of(item)
	reason = _required_text(reason, _("Say why it was cancelled."))
	row = _item_row(item)
	if row.status == "Cancelled":
		frappe.throw(_("This activity is already cancelled."), frappe.ValidationError)
	if row.status == "Done":
		# its Completed visit is a record of work done; cancelling over it would
		# count the one visit both ways
		frappe.throw(
			_("This activity is already done. Hand it back to the matcher first."), frappe.ValidationError
		)
	_refuse_outside_horizon(plan.week_start)

	event = None
	if row.activity_type in EVENT_KINDS:
		day = frappe.utils.getdate(row.planned_date)
		event = _visit_event(
			row.activity_type,
			row.organization,
			datetime.combine(day, time(9, 0)),
			"Cancelled",
			reason,
			row.reference_doctype,
			row.reference_docname,
		)
	frappe.db.set_value(
		"CRM Rep Plan Item",
		item,
		{
			"status": "Cancelled",
			"manual_override": 1,
			"outcome": reason,
			"fulfilled_by_doctype": "Event" if event else None,
			"fulfilled_by": event,
		},
	)
	return get_plan(str(plan.week_start), plan.user)


def _refuse_outside_horizon(week_start) -> None:
	horizon = frappe.utils.getdate() - timedelta(weeks=MATCH_HORIZON_WEEKS)
	if frappe.utils.getdate(week_start) < horizon:
		frappe.throw(_("Plans older than {0} weeks can no longer be edited.").format(MATCH_HORIZON_WEEKS))


@frappe.whitelist()
@sales_user_only
def get_team_week(week_start: str):
	"""Every visible rep's week side by side, for a manager's team calendar.

	Read-only, and scoped exactly like the rep picker (:func:`get_visible_reps`):
	a rep sees only their own row. Plans are read in two queries for the whole
	team rather than one ``get_plan`` per rep.
	"""
	week_start = _monday_or_throw(week_start)
	scope = visible_users()
	filters = {"week_start": week_start}
	if scope is not None:
		filters["user"] = ("in", scope)
	plans = frappe.get_all("CRM Rep Plan", filters=filters, fields=["name", "user"])
	# whoever planned this week has a row, so an old week keeps the rep who has
	# since left; get_visible_reps adds the people with nothing planned yet
	users = sorted({*get_visible_reps(), *(plan.user for plan in plans)})
	# CRM Rep Plan autonames by number, and a child row's parent is a string
	by_plan = {str(plan.name): plan.user for plan in plans}
	rows = (
		frappe.get_all(
			"CRM Rep Plan Item",
			filters={"parenttype": "CRM Rep Plan", "parent": ("in", list(by_plan))},
			fields=["parent", "name", *ITEM_FIELDS],
			order_by="planned_date asc, idx asc",
			limit_page_length=0,
		)
		if by_plan
		else []
	)
	items_by_user: dict[str, list[dict]] = {user: [] for user in users}
	for row in rows:
		user = by_plan[str(row.pop("parent"))]
		items_by_user[user].append(row)
	return {
		"week_start": week_start,
		"reps": [
			{
				"user": user,
				"full_name": frappe.utils.get_fullname(user) or user,
				"items": items_by_user[user],
				"rollup": _rollup(items_by_user[user]),
			}
			for user in users
		],
	}


@frappe.whitelist()
@sales_user_only
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
		payload = _parse_payload(s.action_payload)
		# The payload's activity wins: the suggested_action mapping is lossy
		# (Meeting -> create_task -> Task), so a missed meeting round-tripped
		# as a Task and the matcher then hunted a CRM Task for the meeting the
		# rep actually held. stale_plan payloads carry the original activity.
		activity = payload.get("activity_type")
		if activity not in ACTUAL_SOURCES:
			activity = ACTION_TO_ACTIVITY.get(s.suggested_action, "Task")
		drafts.append(
			{
				"activity_type": activity,
				"planned_date": str(days[i % len(days)]),
				"note": _draft_note(s, payload),
				"reference_doctype": s.reference_doctype,
				"reference_docname": s.reference_docname,
				"suggestion": s.name,
			}
		)
	return drafts


# what the "Log activity" dialog offers: everything a rep can do unplanned
LOGGABLE_TYPES = tuple(kind for kind in ACTIVITY_TYPES if kind not in ("Meeting", "Task"))


@frappe.whitelist()
@sales_user_only
def log_unplanned_visit(
	organization: str | None = None,
	note: str | None = None,
	when: str | None = None,
	reference_doctype: str | None = None,
	reference_docname: str | None = None,
	activity_type: str = "Visit",
):
	"""Record an activity that was never planned -- a rep called to site for a
	breakdown, a delivery dropped off, a phone call -- as already done, in one step.

	A visit, delivery or unplanned meeting creates the calendar Event the matcher
	would have looked for, against the customer; every kind gets a plan item that
	is Done and flagged ``manual_override`` (fulfilled by that event when there is
	one), so the daily job never reconsiders it. The rep's word is the record
	here, exactly as in ``mark_fulfilled``.
	"""
	note = _required_text(note, _("Say what happened."))
	if activity_type not in LOGGABLE_TYPES:
		frappe.throw(_("{0} cannot be logged here.").format(activity_type), frappe.ValidationError)
	if activity_type in EVENT_KINDS and not organization:
		frappe.throw(_("Choose the customer for this {0}.").format(_(activity_type)), frappe.ValidationError)
	if organization and not frappe.db.exists("CRM Organization", organization):
		frappe.throw(_("Organization {0} not found.").format(organization), frappe.DoesNotExistError)
	if reference_doctype and reference_doctype not in REFERENCE_DOCTYPES:
		frappe.throw(_("{0} cannot be the subject of a visit.").format(reference_doctype))
	if not reference_doctype:
		reference_docname = None
	if reference_docname and not _can_reference(reference_doctype, reference_docname):
		frappe.throw(_("You cannot log a visit against that record."), frappe.PermissionError)

	when_dt = frappe.utils.get_datetime(when) if when else frappe.utils.now_datetime()
	if when_dt > frappe.utils.now_datetime():
		# only the lower end of the horizon was checked, so a visit dated next month
		# was written straight in as Done and inflated adherence until its date
		# came round
		frappe.throw(_("A visit cannot be logged before it happens."), frappe.ValidationError)
	if past_days_locked() and when_dt.date() < frappe.utils.getdate():
		frappe.throw(
			_("Activities are logged on the day they happen. {0} has passed.").format(
				frappe.utils.formatdate(when_dt.date())
			),
			frappe.ValidationError,
		)
	monday, _sunday = week_of(when_dt.date())
	horizon = frappe.utils.getdate() - timedelta(weeks=MATCH_HORIZON_WEEKS)
	if monday < horizon:
		frappe.throw(_("Visits older than {0} weeks can no longer be logged.").format(MATCH_HORIZON_WEEKS))

	event = None
	if activity_type in EVENT_KINDS:
		event = _visit_event(
			activity_type, organization, when_dt, "Completed", note, reference_doctype, reference_docname
		)

	user = frappe.session.user
	for attempt in range(2):
		plan = _plan_for(user, str(monday))
		plan.append(
			"items",
			{
				"activity_type": activity_type,
				"planned_date": when_dt.date(),
				# note is a one-line Data field; the whole account is the outcome
				"note": _one_line(note),
				"organization": organization,
				"outcome": note,
				"reference_doctype": reference_doctype,
				"reference_docname": reference_docname,
				"status": "Done",
				"manual_override": 1,
				"fulfilled_by_doctype": "Event" if event else None,
				"fulfilled_by": event,
			},
		)
		frappe.db.savepoint("log_visit")
		try:
			plan.save(ignore_permissions=True)
			break
		except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
			# same race as save_plan: two first saves of one week, the index decides
			frappe.db.rollback(save_point="log_visit")
			if attempt:
				raise
	return get_plan(str(monday), user)


def _one_line(text: str) -> str:
	line = " ".join(text.split())
	return line if len(line) <= NOTE_LIMIT else line[: NOTE_LIMIT - 1].rstrip() + "…"


def _parse_payload(action_payload) -> dict:
	"""A suggestion's ``action_payload`` as a dict, or ``{}`` for anything odd."""
	try:
		payload = json.loads(action_payload or "{}")
	except (ValueError, TypeError):
		payload = {}
	return payload if isinstance(payload, dict) else {}


def _draft_note(suggestion, payload: dict) -> str:
	"""The activity to do, not the reason it is being suggested.

	A suggestion's title addresses the rep ("Overdue plan item: Call Acme"),
	while its payload title is the thing itself ("Call Acme"). Only the payload
	makes sense written on a planner card -- and the ``stale_plan`` signal reads
	plan notes back, so titling the draft from the title nests the prefix a
	little deeper every week it is missed.
	"""
	return (payload.get("title") or suggestion.title or "").strip()


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
