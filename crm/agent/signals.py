# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deterministic signal engine behind CRM Suggestion.

Detection functions are pure -- plain rows and a ``now`` in, suggestion dicts
out -- so thresholds live in tests, not in a running site. ``run_signals`` is
the only frappe-facing entry point: it reads what already exists, expires what
is stale, runs every detector over batched queries (no per-record queries),
drops candidates an open or recently-actioned suggestion already covers, and
inserts the rest one savepoint at a time.

Half the detectors look backwards -- something already went wrong and nobody
noticed. The other half look forwards: ``close_at_risk`` fires while the close
date is still in the future and the stage says it will not be met, and
``deal_cooling`` fires when a deal's own contact cadence decays, days before
the flat idle threshold would trip. That distinction is the point of the tier;
a detector that only reports elapsed time is a report, not a prediction.

This layer is model-free by design (PLAN.md Phase 8, constraint 3): it must
work identically with the agent tier disabled. Nothing here may import
``crm.agent.client``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from itertools import pairwise

import frappe

from crm.agent.config import SIGNAL_DEFAULTS, get_signal_config

# These are the keyword defaults for the pure finders below, and they must be the
# same numbers an admin sees in Settings -- so they are read from SIGNAL_DEFAULTS
# rather than restated. Restating them meant a default changed in one place and
# not the other, with nothing to say the two had parted.
IDLE_DEAL_DAYS = SIGNAL_DEFAULTS["idle_deal_days"]
DISMISS_COOLDOWN_DAYS = SIGNAL_DEFAULTS["dismiss_cooldown_days"]
SUGGESTION_TTL_DAYS = SIGNAL_DEFAULTS["suggestion_ttl_days"]
CLOSE_HORIZON_DAYS = SIGNAL_DEFAULTS["close_horizon_days"]
MAX_OPEN_PER_USER = SIGNAL_DEFAULTS["max_open_per_user"]

# An expiry is nobody's decision, so the signal is allowed back -- but not on the
# next hourly run, or the job would expire and re-create the same row forever.
EXPIRY_COOLDOWN_DAYS = 7

# A rep who dismisses the same signal repeatedly is telling us the threshold is
# wrong for them; the cooldown stretches by one multiple per dismissal, capped so
# a signal never goes away permanently on the strength of a bad week.
MAX_COOLDOWN_MULTIPLIER = 4

# Stage probability (from CRM Deal Status) below which a deal counts as early.
EARLY_STAGE_PROBABILITY = 60

# Cadence decay: a gap this many times the deal's own median gap, and at least
# COOLING_MIN_GAP_DAYS wide, is a deal going quiet. Below MIN_CADENCE_POINTS
# touches there is no cadence to compare against and nothing is claimed.
COOLING_RATIO = 2.0
COOLING_MIN_GAP_DAYS = 2
MIN_CADENCE_POINTS = 3
CADENCE_WINDOW_DAYS = 60

# Plan items older than this are the matcher's problem, not a fresh signal.
STALE_PLAN_HORIZON_WEEKS = 4

# CRM Suggestion.title is Data(140). An organization name is Data(140) too, so an
# unclipped label overflows the title and raises out of the insert.
TITLE_MAX_LENGTH = 140
LABEL_MAX_LENGTH = 90

BATCH_SIZE = 1000
COMMIT_EVERY = 200
MAX_NEW_PER_RUN = 5000
PURGE_AFTER_DAYS = 90

# Suggestion urgency, 0-100. The inbox is ordered by this number, so between them
# these decide what every rep looks at first -- which makes them the tuning
# surface, and predict.py's rule applies here too: a tuning surface nobody can
# find is not one. They were literals inside the emitted dicts, six of them,
# where changing the relative order of two signals meant reading six functions.
#
# Flat scores are a judgement about the signal itself; the graduated ones rise
# with the evidence, and every one of them is capped, so no single signal can
# monopolise the top of the inbox by growing without bound.
IDLE_SCORE_PER_DAY = 10.0
IDLE_SCORE_CAP = 100.0

NO_NEXT_STEP_SCORE = 40.0

SLA_BREACH_SCORE = 80.0

# Rises as the close date approaches: the nearer the date, the less time is left
# to act on it.
CLOSE_RISK_SCORE_BASE = 50.0
CLOSE_RISK_SCORE_PER_DAY_CLOSER = 3.0
CLOSE_RISK_SCORE_CAP = 95.0

COOLING_SCORE_BASE = 30.0
COOLING_SCORE_PER_RATIO = 10.0
COOLING_SCORE_CAP = 75.0

# Base plus lateness, so a plan item missed by a week outranks one missed
# yesterday, but never outranks an SLA breach.
PLAN_MISSED_SCORE_BASE = 55.0
PLAN_MISSED_SCORE_PER_DAY_LATE = 2.0
PLAN_MISSED_LATENESS_CAP = 20.0

ACTIVITY_TO_ACTION = {"Call": "schedule_call", "Email": "send_reply", "Meeting": "create_task"}


def _label(value, fallback: str) -> str:
	return str(value or fallback)[:LABEL_MAX_LENGTH]


def cadence_ratio(history: list[datetime], now: datetime) -> tuple[float, float, float] | None:
	"""How far the current silence has stretched past this record's own rhythm.

	Returns ``(ratio, gap_days, median_gap_days)`` or None when there are too few
	touches to have a rhythm at all. The baseline is the median gap between the
	historical touches, so one long holiday gap does not become the norm.
	"""
	points = sorted(t for t in history if t)
	if len(points) < MIN_CADENCE_POINTS:
		return None
	gaps = [(later - earlier).total_seconds() / 86400.0 for earlier, later in pairwise(points)]
	gaps = [g for g in gaps if g > 0]
	if not gaps:
		return None
	gaps.sort()
	middle = len(gaps) // 2
	median = gaps[middle] if len(gaps) % 2 else (gaps[middle - 1] + gaps[middle]) / 2
	if median <= 0:
		return None
	gap_days = (now - points[-1]).total_seconds() / 86400.0
	return gap_days / median, gap_days, median


def find_idle_deals(
	rows: list[dict],
	activity: dict[str, datetime],
	now: datetime,
	idle_days: int = IDLE_DEAL_DAYS,
) -> list[dict]:
	"""Open/ongoing deals with no recorded activity for ``idle_days``.

	``activity`` maps deal name -> latest activity datetime; a deal absent from
	it falls back to its creation date, so a deal never touched still ages.
	"""
	out = []
	threshold = now - timedelta(days=idle_days)
	for row in rows:
		last = activity.get(row["name"]) or row["creation"]
		if last > threshold:
			continue
		elapsed = (now - last).days
		label = _label(row.get("organization"), row["name"])
		out.append(
			{
				"signal": "idle_deal",
				"title": f"Re-engage {label}",
				"reference_doctype": "CRM Deal",
				"reference_docname": row["name"],
				"user": row.get("deal_owner"),
				"suggested_action": "create_task",
				"action_payload": {"title": f"Re-engage {label}"},
				"rationale": f"No activity on this deal for {elapsed} days.",
				"factors": [
					{
						"key": "idle_days",
						"label": f"No activity for {elapsed} days",
						"value": elapsed,
					}
				],
				"score": min(IDLE_SCORE_CAP, elapsed * IDLE_SCORE_PER_DAY),
			}
		)
	return out


def find_missing_next_step(rows: list[dict], open_tasks: set[str]) -> list[dict]:
	"""Open/ongoing deals with no open task and no ``next_step`` set."""
	out = []
	for row in rows:
		if row["name"] in open_tasks or (row.get("next_step") or "").strip():
			continue
		label = _label(row.get("organization"), row["name"])
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
				"factors": [
					{"key": "has_open_task", "label": "No open task", "value": False},
					{"key": "has_next_step", "label": "No next step recorded", "value": False},
				],
				"score": NO_NEXT_STEP_SCORE,
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
		label = _label(row.get("lead_name"), row["name"])
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
				"factors": [
					{
						"key": "sla_status",
						"label": f"SLA status is {row.get('sla_status')}",
						"value": row.get("sla_status"),
					}
				],
				"score": SLA_BREACH_SCORE,
			}
		)
	return out


def find_close_date_at_risk(
	rows: list[dict],
	open_tasks: set[str],
	now: datetime,
	horizon_days: int = CLOSE_HORIZON_DAYS,
) -> list[dict]:
	"""Deals due to close soon that are nowhere near closeable.

	Forward-looking by construction: the test is against the *expected* close
	date while it is still ahead, combined with the stage's own probability and
	the absence of anything scheduled. A deal whose close date has already
	slipped is history -- this fires while the rep can still move it.

	Rows carry ``expected_closure_date``, ``status`` and ``stage_probability``
	(the CRM Deal Status probability, which is the site's own definition of how
	far along a stage is, so no hardcoded stage names appear here).
	"""
	out = []
	today = now.date()
	for row in rows:
		due = row.get("expected_closure_date")
		if not due:
			continue
		days_to_close = (due - today).days
		if days_to_close > horizon_days:
			continue
		probability = row.get("stage_probability")
		if probability is None or probability >= EARLY_STAGE_PROBABILITY:
			continue
		if row["name"] in open_tasks:
			continue
		label = _label(row.get("organization"), row["name"])
		when = f"in {days_to_close} days" if days_to_close >= 0 else f"{-days_to_close} days ago"
		out.append(
			{
				"signal": "close_at_risk",
				"title": f"Close date at risk for {label}",
				"reference_doctype": "CRM Deal",
				"reference_docname": row["name"],
				"user": row.get("deal_owner"),
				"suggested_action": "schedule_call",
				"action_payload": {"title": f"Confirm the close plan for {label}"},
				"rationale": (
					f"Expected to close {when} but still at {row.get('status')} "
					f"({probability:g}% stage probability) with nothing scheduled."
				),
				"factors": [
					{
						"key": "days_to_close",
						"label": f"Expected close {when}",
						"value": days_to_close,
					},
					{
						"key": "stage_probability",
						"label": f"Stage {row.get('status')} closes {probability:g}% of the time",
						"value": probability,
					},
					{"key": "has_open_task", "label": "Nothing scheduled", "value": False},
				],
				"score": min(
					CLOSE_RISK_SCORE_CAP,
					CLOSE_RISK_SCORE_BASE + (horizon_days - days_to_close) * CLOSE_RISK_SCORE_PER_DAY_CLOSER,
				),
			}
		)
	return out


def find_cooling_deals(
	rows: list[dict],
	history: dict[str, list[datetime]],
	now: datetime,
	idle_days: int = IDLE_DEAL_DAYS,
) -> list[dict]:
	"""Deals whose contact cadence is decaying against their own history.

	A deal touched daily for a month and then not for four days is in trouble,
	but no elapsed-time threshold sees it -- ``idle_deal`` will not fire for
	another three days, and by then the pattern is a week old. Comparing the
	current gap to the deal's own median gap catches the deceleration instead of
	the outage, which is the difference between predicting and reporting.

	Deals already past the idle threshold are left to ``find_idle_deals``; there
	is no value in two suggestions saying the same thing.
	"""
	out = []
	for row in rows:
		measured = cadence_ratio(history.get(row["name"]) or [], now)
		if not measured:
			continue
		ratio, gap_days, median_gap = measured
		if gap_days >= idle_days or gap_days < COOLING_MIN_GAP_DAYS or ratio < COOLING_RATIO:
			continue
		label = _label(row.get("organization"), row["name"])
		out.append(
			{
				"signal": "deal_cooling",
				"title": f"{label} is going quiet",
				"reference_doctype": "CRM Deal",
				"reference_docname": row["name"],
				"user": row.get("deal_owner"),
				"suggested_action": "create_task",
				"action_payload": {"title": f"Check in with {label}"},
				"rationale": (
					f"This deal was touched every {median_gap:.1f} days on average and "
					f"has now been quiet for {gap_days:.1f}."
				),
				"factors": [
					{
						"key": "gap_days",
						"label": f"Quiet for {gap_days:.1f} days",
						"value": round(gap_days, 1),
					},
					{
						"key": "median_gap_days",
						"label": f"Usually touched every {median_gap:.1f} days",
						"value": round(median_gap, 1),
					},
					{
						"key": "cadence_ratio",
						"label": f"{ratio:.1f}x slower than this deal's own rhythm",
						"value": round(ratio, 2),
					},
				],
				"score": min(COOLING_SCORE_CAP, COOLING_SCORE_BASE + ratio * COOLING_SCORE_PER_RATIO),
			}
		)
	return out


def find_stale_plan_items(rows: list[dict], now: datetime) -> list[dict]:
	"""Plan items that were missed, or planned for a day that has passed.

	Closes the plan -> suggestion loop: a Missed item otherwise surfaces only in
	the Planner grid. Items with no linked record are skipped -- the suggestion
	is an instruction to act on something, and there is nothing to act on.
	"""
	out = []
	today = now.date()
	for row in rows:
		if not (row.get("reference_doctype") and row.get("reference_docname")):
			continue
		planned = row.get("planned_date")
		missed = row.get("status") == "Missed"
		overdue = row.get("status") == "Planned" and planned and planned < today
		if not (missed or overdue):
			continue
		activity = row.get("activity_type") or "Task"
		label = _label(row.get("note"), f"{activity} on {row['reference_docname']}")
		late = (today - planned).days if planned else None
		out.append(
			{
				"signal": "stale_plan",
				"title": f"Overdue plan item: {label}",
				"reference_doctype": row["reference_doctype"],
				"reference_docname": row["reference_docname"],
				"user": row.get("user"),
				"suggested_action": ACTIVITY_TO_ACTION.get(activity, "create_task"),
				"action_payload": {"title": label},
				"rationale": (
					f"You planned this {activity.lower()} for {planned} and it is still open."
					if planned
					else f"You planned this {activity.lower()} and it was marked missed."
				),
				"factors": [
					{
						"key": "plan_status",
						"label": f"Plan item is {row.get('status')}",
						"value": row.get("status"),
					},
					{"key": "days_late", "label": f"{late} days past the planned date", "value": late},
				],
				"score": PLAN_MISSED_SCORE_BASE
				+ min(PLAN_MISSED_LATENESS_CAP, (late or 0) * PLAN_MISSED_SCORE_PER_DAY_LATE),
			}
		)
	return out


def dismissal_cooldown(base_days: int, dismissals: int) -> int:
	"""Cooldown for a rep who has already said no to this signal ``dismissals`` times."""
	return base_days * min(1 + max(0, dismissals), MAX_COOLDOWN_MULTIPLIER)


def _blocks(row: dict, now: datetime, cooldown_days: int) -> bool:
	if row["status"] == "Open":
		return True
	if row["status"] in ("Dismissed", "Accepted"):
		return row["modified"] > now - timedelta(days=cooldown_days)
	if row["status"] == "Expired":
		return row["modified"] > now - timedelta(days=EXPIRY_COOLDOWN_DAYS)
	return False


def dedupe(
	candidates: list[dict],
	existing: list[dict],
	now: datetime,
	cooldown_days: int = DISMISS_COOLDOWN_DAYS,
	dismissals: dict[tuple[str, str], int] | None = None,
) -> list[dict]:
	"""Drop candidates already covered by an existing suggestion.

	Open suggestions always block. Dismissed and Accepted ones block for a
	cooldown after their last change -- a rep who said "no" (or already acted) is
	not nagged about the same record twice in that window. ``dismissals`` maps
	(user, signal) to how often that rep has dismissed that signal anywhere, and
	stretches their cooldown accordingly: the queue learns from the dismissals
	instead of only recording them. Expired rows block for the shorter
	EXPIRY_COOLDOWN_DAYS so the job cannot expire and re-create a row in a loop.
	"""
	dismissals = dismissals or {}
	by_key: dict[tuple[str, str], list[dict]] = {}
	for row in existing:
		by_key.setdefault((row["signal"], row["reference_docname"]), []).append(row)

	out = []
	for candidate in candidates:
		key = (candidate["signal"], candidate["reference_docname"])
		cooldown = dismissal_cooldown(
			cooldown_days, dismissals.get((candidate.get("user"), candidate["signal"]), 0)
		)
		if any(_blocks(row, now, cooldown) for row in by_key.get(key, ())):
			continue
		out.append(candidate)
	return out


def _rank_key(candidate: dict) -> tuple:
	"""Highest score first, then a stable tie-break.

	Score alone is not an ordering: ``no_next_step`` gives every candidate the
	same 40, so a sort on score would keep whichever rows the deal query
	happened to return first and reshuffle them the next hour. The signal and
	record names make the choice reproducible.
	"""
	return (-float(candidate.get("score") or 0), candidate["signal"], candidate["reference_docname"])


def cap_per_user(candidates: list[dict], open_counts: dict[str, int], cap: int) -> list[dict]:
	"""Keep only the highest-scoring candidates that fit under each rep's ceiling.

	An inbox is a ranked worklist, not a census. ``no_next_step`` fires on every
	open deal with no task, so an org that imports its pipeline gets one
	suggestion per deal -- and the inbox only ever renders 50 rows, so the rest
	are written, counted in the badge, and unreadable by anyone. Ranking here
	rather than at read time is deliberate: the rows that would not fit are not
	stored at all, so the badge, the query, and the hourly job all shrink
	together.

	``open_counts`` is what each user already has open, so a rep sitting on a
	full inbox gets nothing new until they work it down. Candidates with no
	owner share one bucket: nobody's queue is still a queue, and a manager
	reading the unscoped list should not be handed the whole backlog either.
	"""
	room = {}
	out = []
	for candidate in sorted(candidates, key=_rank_key):
		user = candidate.get("user") or ""
		if user not in room:
			room[user] = max(0, cap - open_counts.get(user, 0))
		if room[user] <= 0:
			continue
		room[user] -= 1
		out.append(candidate)
	return out


# --- frappe-facing layer -------------------------------------------------


def _batched(values: list, size: int = BATCH_SIZE) -> Iterator[list]:
	"""Chunk an IN clause. A site-wide scan puts every deal name in one query."""
	for start in range(0, len(values), size):
		yield values[start : start + size]


def _stage_probability() -> dict[str, float]:
	"""CRM Deal Status -> probability, the site's own measure of stage progress."""
	return {
		row["name"]: frappe.utils.flt(row["probability"])
		for row in frappe.get_all("CRM Deal Status", fields=["name", "probability"])
	}


def _working_deal_rows() -> list[dict]:
	statuses = frappe.get_all("CRM Deal Status", filters={"type": ("in", ("Open", "Ongoing"))}, pluck="name")
	if not statuses:
		return []
	probability = _stage_probability()
	rows = frappe.get_all(
		"CRM Deal",
		filters={"status": ("in", statuses)},
		fields=[
			"name",
			"organization",
			"deal_owner",
			"next_step",
			"status",
			"expected_closure_date",
			"creation",
		],
	)
	for row in rows:
		row["stage_probability"] = probability.get(row["status"])
	return rows


ACTIVITY_SOURCES = (
	("Communication", "reference_name", "creation"),
	("CRM Task", "reference_docname", "modified"),
	("CRM Call Log", "reference_docname", "modified"),
	("Comment", "reference_name", "creation"),
)


def _activity_query(doctype: str, ref_field: str, deal_names: list[str]):
	table = frappe.qb.DocType(doctype)
	query = (
		frappe.qb.from_(table)
		.where(table.reference_doctype == "CRM Deal")
		.where(table[ref_field].isin(deal_names))
	)
	if doctype == "Comment":
		# only human comments count as activity — assignment/share/system
		# comments would reset the idle clock on every automation
		query = query.where(table.comment_type == "Comment")
	return table, query


def _latest_activity(deal_names: list[str]) -> dict[str, datetime]:
	"""Latest touch per deal across every activity source, batched per source."""
	if not deal_names:
		return {}
	from frappe.query_builder.functions import Max

	latest: dict[str, datetime] = {}
	for doctype, ref_field, when_field in ACTIVITY_SOURCES:
		for batch in _batched(deal_names):
			table, query = _activity_query(doctype, ref_field, batch)
			rows = (
				query.select(table[ref_field].as_("ref"), Max(table[when_field]).as_("last"))
				.groupby(table[ref_field])
				.run(as_dict=True)
			)
			for row in rows:
				if row["last"] and (row["ref"] not in latest or row["last"] > latest[row["ref"]]):
					latest[row["ref"]] = row["last"]
	return latest


def _activity_history(deal_names: list[str], since: datetime) -> dict[str, list[datetime]]:
	"""Every touch per deal inside the cadence window, batched per source.

	Bounded twice over: callers pass only deals that were touched recently (a
	silent deal has no cadence left to measure and is the idle detector's job),
	and the window caps how far back a row can come from.
	"""
	if not deal_names:
		return {}
	history: dict[str, list[datetime]] = {}
	for doctype, ref_field, when_field in ACTIVITY_SOURCES:
		for batch in _batched(deal_names):
			table, query = _activity_query(doctype, ref_field, batch)
			rows = (
				query.select(table[ref_field].as_("ref"), table[when_field].as_("when"))
				.where(table[when_field] >= since)
				.run(as_dict=True)
			)
			for row in rows:
				if row["when"]:
					history.setdefault(row["ref"], []).append(row["when"])
	return history


def _deals_with_open_tasks(deal_names: list[str]) -> set[str]:
	if not deal_names:
		return set()
	found: set[str] = set()
	for batch in _batched(deal_names):
		found.update(
			frappe.get_all(
				"CRM Task",
				filters={
					"reference_doctype": "CRM Deal",
					"reference_docname": ("in", batch),
					"status": ("not in", ("Done", "Canceled")),
				},
				pluck="reference_docname",
			)
		)
	return found


def _sla_lead_rows() -> list[dict]:
	"""Leads still worth chasing: a Lost or Junk lead's breached SLA is not news."""
	statuses = frappe.get_all("CRM Lead Status", filters={"type": ("in", ("Open", "Ongoing"))}, pluck="name")
	if not statuses:
		return []
	return frappe.get_all(
		"CRM Lead",
		filters={
			"converted": 0,
			"sla": ("is", "set"),
			"status": ("in", statuses),
			"lead_owner": ("is", "set"),
		},
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


def _stale_plan_rows(now: datetime) -> list[dict]:
	item = frappe.qb.DocType("CRM Rep Plan Item")
	plan = frappe.qb.DocType("CRM Rep Plan")
	horizon = now.date() - timedelta(weeks=STALE_PLAN_HORIZON_WEEKS)
	return (
		frappe.qb.from_(item)
		.join(plan)
		.on(item.parent == plan.name)
		.select(
			item.activity_type,
			item.planned_date,
			item.note,
			item.status,
			item.reference_doctype,
			item.reference_docname,
			plan.user,
		)
		.where(item.status.isin(("Planned", "Missed")))
		.where(item.reference_docname.notnull())
		.where(plan.week_start >= horizon)
		.run(as_dict=True)
	)


def _existing_suggestions(reference_docnames: list[str]) -> list[dict]:
	rows: list[dict] = []
	for batch in _batched(sorted(set(reference_docnames))):
		rows += frappe.get_all(
			"CRM Suggestion",
			filters={"reference_docname": ("in", batch)},
			fields=["signal", "reference_docname", "status", "modified"],
		)
	return rows


def _dismissal_counts(candidates: list[dict]) -> dict[tuple[str, str], int]:
	"""How often each rep has dismissed each signal, for the growing cooldown.

	This is what makes ``dismiss_reason`` more than a write-only field: the
	counts feed back into dedupe, and ``crm.api.suggestions.get_dismissal_stats``
	reads the same rows so an admin can see which threshold to move.
	"""
	users = sorted({c["user"] for c in candidates if c.get("user")})
	signals = sorted({c["signal"] for c in candidates})
	if not users or not signals:
		return {}
	from frappe.query_builder.functions import Count

	table = frappe.qb.DocType("CRM Suggestion")
	rows = (
		frappe.qb.from_(table)
		.select(table.user, table.signal, Count(table.name).as_("dismissals"))
		.where(table.status == "Dismissed")
		.where(table.user.isin(users))
		.where(table.signal.isin(signals))
		.groupby(table.user, table.signal)
		.run(as_dict=True)
	)
	return {(row["user"], row["signal"]): row["dismissals"] for row in rows}


def expire_stale(now: datetime) -> int:
	"""Flip every overdue open suggestion in one statement, touching ``modified``.

	The timestamp is what the expiry cooldown in ``dedupe`` reads, so it has to
	move even though nobody edited the row.
	"""
	table = frappe.qb.DocType("CRM Suggestion")
	return (
		frappe.qb.update(table)
		.set(table.status, "Expired")
		.set(table.modified, now)
		.where(table.status == "Open")
		.where(table.expires_on.isnotnull())
		.where(table.expires_on < now)
	).run()


def _open_counts() -> dict[str, int]:
	"""How many open suggestions each rep is already carrying.

	Keyed by user with the unowned rows under ``""``, which is the same bucket
	``cap_per_user`` uses -- a deal with no owner still produces candidates, and
	they have to be counted somewhere.
	"""
	from frappe.query_builder.functions import Count

	table = frappe.qb.DocType("CRM Suggestion")
	rows = (
		frappe.qb.from_(table)
		.select(table.user, Count(table.name).as_("open"))
		.where(table.status == "Open")
		.groupby(table.user)
		.run(as_dict=True)
	)
	return {(row["user"] or ""): row["open"] for row in rows}


def trim_open_over_cap(now: datetime, cap: int = MAX_OPEN_PER_USER) -> int:
	"""Expire the lowest-ranked open rows for any rep already over the ceiling.

	``cap_per_user`` keeps a queue from growing past the cap, but it cannot
	shrink one that is already over -- a site that ran before the cap existed,
	or whose admin has just lowered it, keeps its backlog forever otherwise.
	This is the other half of the same rule, applied to rows already on disk.

	Which rows survive is deliberate and must not change between runs: the
	ranking is score first, then oldest first, then name. ``creation`` and
	``name`` never move, so the same rows survive every hour instead of the
	inbox reshuffling itself under a rep who is working through it.
	"""
	expired = 0
	table = frappe.qb.DocType("CRM Suggestion")
	for user, count in sorted(_open_counts().items()):
		if count <= cap:
			continue
		owner = table.user.isnull() | (table.user == "") if not user else table.user == user
		names = (
			frappe.qb.from_(table)
			.select(table.name)
			.where(table.status == "Open")
			.where(owner)
			.orderby(table.score)
			.orderby(table.creation, order=frappe.qb.desc)
			.orderby(table.name, order=frappe.qb.desc)
			.limit(count - cap)
			.run(pluck=True)
		)
		for batch in _batched(names):
			# the row count comes from the batch, not from run(): a query-builder
			# UPDATE returns a tuple, and adding that to an int is a TypeError
			(
				frappe.qb.update(table)
				.set(table.status, "Expired")
				.set(table.modified, now)
				.where(table.name.isin(batch))
			).run()
			expired += len(batch)
	return expired


def _collect_candidates(now: datetime, cfg) -> list[dict]:
	deals = _working_deal_rows()
	deal_names = [d["name"] for d in deals]
	activity = _latest_activity(deal_names)
	open_tasks = _deals_with_open_tasks(deal_names)

	# only deals still being touched can be decelerating; the rest are idle
	recent = [
		name for name in deal_names if activity.get(name) and (now - activity[name]).days < cfg.idle_deal_days
	]
	history = _activity_history(recent, now - timedelta(days=CADENCE_WINDOW_DAYS))

	return (
		find_idle_deals(deals, activity, now, cfg.idle_deal_days)
		+ find_missing_next_step(deals, open_tasks)
		+ find_close_date_at_risk(deals, open_tasks, now, cfg.close_horizon_days)
		+ find_cooling_deals(deals, history, now, cfg.idle_deal_days)
		+ find_sla_breached_leads(_sla_lead_rows(), now)
		+ find_stale_plan_items(_stale_plan_rows(now), now)
	)


def run_signals() -> int:
	"""Scheduler entry point. Returns how many suggestions were created."""
	cfg = get_signal_config()
	if not cfg.signals_enabled:
		return 0

	now = frappe.utils.now_datetime()
	candidates = _collect_candidates(now, cfg)

	# read the existing rows before expiring anything: a row that expires in this
	# run must still block, or the job re-creates what it just expired
	existing = _existing_suggestions([c["reference_docname"] for c in candidates]) if candidates else []
	expire_stale(now)
	trim_open_over_cap(now, cfg.max_open_per_user)
	if not candidates:
		return 0

	fresh = dedupe(candidates, existing, now, cfg.dismiss_cooldown_days, _dismissal_counts(candidates))
	# after expiring and trimming, so the room each rep has left is the real one
	fresh = cap_per_user(fresh, _open_counts(), cfg.max_open_per_user)
	expires_on = now + timedelta(days=cfg.suggestion_ttl_days)

	created = 0
	notify: set[str] = set()
	for candidate in fresh[:MAX_NEW_PER_RUN]:
		if _insert_suggestion(candidate, expires_on):
			created += 1
			if candidate.get("user"):
				notify.add(candidate["user"])
			# a long run should not hold every row in one transaction; tests run
			# inside one and roll it back, so committing there would leak fixtures
			if created % COMMIT_EVERY == 0 and not frappe.flags.in_test:
				frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	if created and not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	publish_new_suggestions(notify)
	return created


def publish_new_suggestions(users) -> None:
	"""Tell each affected rep their inbox changed, once per run rather than per row.

	A proactive surface that only refreshes when clicked is not proactive — but a
	run that creates 80 suggestions must not emit 80 events either, so this fires
	one per user. The payload is deliberately empty: the client refetches through
	the scoped endpoint, so nothing another rep may not see travels over the wire.
	"""
	for user in users:
		frappe.publish_realtime("crm_suggestion", user=user, after_commit=True)


def _insert_suggestion(candidate: dict, expires_on: datetime) -> bool:
	"""Insert one suggestion, isolated. A bad row costs its own row and nothing else.

	Titles are built from user-supplied names and the owner is a Link to a User
	that may since have been deleted, so an insert here can and does raise --
	without the savepoint one such record aborts the whole hourly run and rolls
	back every suggestion it had already created.
	"""
	frappe.db.savepoint("crm_signal_insert")
	try:
		doc = dict(
			candidate,
			doctype="CRM Suggestion",
			title=candidate["title"][:TITLE_MAX_LENGTH],
			action_payload=json.dumps(candidate["action_payload"]),
			factors=json.dumps(candidate["factors"]),
			expires_on=expires_on,
		)
		frappe.get_doc(doc).insert(ignore_permissions=True)
		return True
	except Exception:
		frappe.db.rollback(save_point="crm_signal_insert")
		frappe.log_error(
			title="CRM signal insert failed",
			message=f"{candidate.get('signal')} on {candidate.get('reference_docname')}\n\n"
			+ frappe.get_traceback(),
		)
		return False


def purge_old_suggestions(limit: int = 5000) -> int:
	"""Daily scheduler entry: settled suggestions stop being evidence eventually.

	Rows a rep plan item still points at are kept whatever their age -- deleting
	one would leave the planner with a dangling link to explain.
	"""
	cutoff = frappe.utils.add_days(frappe.utils.now_datetime(), -PURGE_AFTER_DAYS)
	names = frappe.get_all(
		"CRM Suggestion",
		filters={"status": ("in", ("Expired", "Dismissed")), "modified": ("<", cutoff)},
		pluck="name",
		limit=limit,
	)
	if not names:
		return 0
	linked = set(
		frappe.get_all("CRM Rep Plan Item", filters={"suggestion": ("in", names)}, pluck="suggestion")
	)
	names = [name for name in names if name not in linked]
	for batch in _batched(names):
		frappe.db.delete("CRM Suggestion", {"name": ("in", batch)})
	return len(names)


def clear_suggestions_for(doctype: str, docname: str) -> None:
	"""Drop a record's suggestions when the record goes.

	``ignore_links_on_delete`` lets the deal be deleted; without this the rows it
	leaves behind point at nothing and still show up in an inbox.
	"""
	frappe.db.delete("CRM Suggestion", {"reference_doctype": doctype, "reference_docname": docname})


def resync_owner(doctype: str, docname: str, user: str | None) -> None:
	"""Move a record's open suggestions to whoever owns it now.

	A reassigned deal used to keep nagging the previous rep for the rest of the
	TTL while being invisible to the one who inherited it -- the opposite of
	proactive for both of them.
	"""
	frappe.db.set_value(
		"CRM Suggestion",
		{"reference_doctype": doctype, "reference_docname": docname, "status": "Open"},
		"user",
		user,
		update_modified=False,
	)
