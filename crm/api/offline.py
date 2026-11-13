# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Field mode: what a rep's phone carries to a site with no reception.

Two reads, and nothing here writes.

:func:`get_pack` is the snapshot the phone keeps: the caller's weeks, the
customers they may see with the people and open deals at them, what happened
on recent visits, their open tasks. Every list in it is read with
``frappe.get_list``, so the row scoping in ``crm/permissions`` decides what a
rep carries exactly as it decides what a rep sees online -- the pack is not a
second access path with rules of its own. The one exception is the caller's
own plan rows, read by parent and pinned to ``frappe.session.user``.

It is a full snapshot rather than a diff. A rep carries a few hundred rows; a
cursor would have to get deletions and a customer handed to another rep right,
and the cost of getting those wrong is a phone showing a customer the rep no
longer has. The hash lets a phone on a bad line skip a download that would
change nothing.

:func:`handshake` is how the cached shell gets going again. The shell is
served by the service worker with no boot in it, so it has no CSRF token; this
returns the session's token and the server clock, over GET so it needs no
token to ask for one. It is only readable same-origin, like the page the token
is normally inlined in.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import timedelta

import frappe

from crm.api.rep_plan import ITEM_FIELDS, LOGGABLE_TYPES, get_plan, past_days_locked
from crm.rep_planning import ACTIVITY_TYPES, EVENT_KINDS, MATCH_HORIZON_WEEKS, week_of
from crm.utils import sales_user_only

# How far back a phone carries what happened at a customer. Also the window a
# lost phone exposes, which is why it is not "everything".
HISTORY_DAYS = 90

# The phone drops its copy after this long without a successful sync. Sent in
# the pack so the client and the server cannot disagree about the number.
PACK_MAX_AGE_DAYS = 14

# Set by crm/www/crm.py on every page render, deleted on logout: the user a
# cached shell may show a saved copy for. Mirrored in the frontend's
# offline/bootSnapshot.js.
FIELD_USER_COOKIE = "crm_field_user"

# Row caps. Far above what one rep carries (MBP's busiest holds a few hundred
# customers); they bound the payload for a manager on a large site, and
# `truncated` says so rather than letting a short list pass for a complete one.
MAX_ORGANIZATIONS = 3000
MAX_CONTACTS = 6000
MAX_DEALS = 3000
MAX_HISTORY = 3000
MAX_NOTES = 500
MAX_TASKS = 500

# Long text is cut on the way out: the phone shows a note, it does not edit one.
TEXT_LIMIT = 2000

CLOSED_DEAL_TYPES = ("Won", "Lost")
OPEN_TASK_STATUSES = ("Backlog", "Todo", "In Progress", "Rescheduled")
NOTE_DOCTYPES = ("CRM Organization", "CRM Deal")


@frappe.whitelist(methods=["GET"])
@sales_user_only
def handshake() -> dict:
	"""The session's CSRF token and the server clock, for a shell that booted without them."""
	return {
		"user": frappe.session.user,
		"csrf_token": frappe.sessions.get_csrf_token(),
		# the site clock, which is the one every "not before it happens" check
		# reads, and the instant as a number so the phone can measure how far
		# its own clock is out without knowing the site's timezone
		"server_time": _stamp(frappe.utils.now_datetime()),
		"server_epoch": int(time.time()),
	}


@frappe.whitelist()
@sales_user_only
def get_pack(known_hash: str | None = None) -> dict:
	"""Everything the caller's phone needs to work a site visit offline.

	Pass the ``hash`` of the pack already held to be told ``unchanged`` instead
	of being sent the same rows again.
	"""
	body = _pack_body()
	digest = hashlib.sha256(
		json.dumps(body, sort_keys=True, default=str, separators=(",", ":")).encode()
	).hexdigest()

	envelope = {
		"user": frappe.session.user,
		"hash": digest,
		"generated_at": _stamp(frappe.utils.now_datetime()),
		"today": str(frappe.utils.getdate()),
		"max_age_days": PACK_MAX_AGE_DAYS,
	}
	if known_hash and known_hash == digest:
		return {**envelope, "unchanged": True}
	return {**envelope, "unchanged": False, **body}


def _pack_body() -> dict:
	today = frappe.utils.getdate()
	since = today - timedelta(days=HISTORY_DAYS)

	organizations = _organizations()
	contacts = _contacts(organizations)
	deals = _deals()
	history = _history(since)
	notes = _notes(since)
	tasks = _tasks()

	truncated = [
		label
		for label, rows, cap in (
			("organizations", organizations, MAX_ORGANIZATIONS),
			("contacts", contacts, MAX_CONTACTS),
			("deals", deals, MAX_DEALS),
			("history", history, MAX_HISTORY),
			("notes", notes, MAX_NOTES),
			("tasks", tasks, MAX_TASKS),
		)
		if len(rows) >= cap
	]

	return {
		"rules": {
			"activity_types": list(ACTIVITY_TYPES),
			"loggable_types": list(LOGGABLE_TYPES),
			"event_kinds": list(EVENT_KINDS),
			"lock_past_plans": bool(past_days_locked()),
			"horizon_weeks": MATCH_HORIZON_WEEKS,
			"history_days": HISTORY_DAYS,
		},
		"plans": _plans(today),
		"organizations": organizations,
		"contacts": contacts,
		"deals": deals,
		"history": history,
		"notes": notes,
		"tasks": tasks,
		"truncated": truncated,
	}


def _plans(today) -> list[dict]:
	"""Last week, this week and next: what a rep on site looks back and ahead at."""
	monday, _sunday = week_of(today)
	weeks = [monday + timedelta(weeks=offset) for offset in (-1, 0, 1)]
	return [get_plan(str(week)) for week in weeks]


def _organizations() -> list[dict]:
	rows = frappe.get_list(
		"CRM Organization",
		fields=["name", "organization_name", "website", "industry", "territory", "account_owner", "address"],
		order_by="organization_name asc",
		limit=MAX_ORGANIZATIONS,
	)
	addresses = _addresses({row.address for row in rows if row.address})
	for row in rows:
		row["address"] = addresses.get(row.pop("address", None))
	return rows


def _addresses(names: set[str]) -> dict[str, dict]:
	if not names:
		return {}
	rows = frappe.get_list(
		"Address",
		filters={"name": ("in", sorted(names))},
		fields=["name", "address_line1", "address_line2", "city", "state", "pincode", "country", "phone"],
		limit=len(names),
	)
	return {row.pop("name"): row for row in rows}


def _contacts(organizations: list[dict]) -> list[dict]:
	"""The people at the customers being carried, and nobody else.

	A rep can read more contacts than these online -- anyone with no company,
	or a company typed as free text -- but a phone has no use for them at a
	site, and what is not on it cannot be lost with it. ``company_name`` holds
	the customer's record name on most rows and its display name on some, so
	both are matched, as the row scoping does.
	"""
	companies = {row.name for row in organizations} | {
		row.organization_name for row in organizations if row.organization_name
	}
	if not companies:
		return []
	return frappe.get_list(
		"Contact",
		filters={"company_name": ("in", sorted(companies))},
		fields=["name", "full_name", "company_name", "designation", "email_id", "mobile_no", "phone"],
		order_by="full_name asc",
		limit=MAX_CONTACTS,
	)


def _deals() -> list[dict]:
	closed = frappe.get_all("CRM Deal Status", filters={"type": ("in", CLOSED_DEAL_TYPES)}, pluck="name")
	filters = {"status": ("not in", closed)} if closed else {}
	return frappe.get_list(
		"CRM Deal",
		filters=filters,
		fields=[
			"name",
			"organization",
			"status",
			"deal_value",
			"currency",
			"expected_closure_date",
			"next_step",
			"deal_owner",
			"modified",
		],
		order_by="modified desc",
		limit=MAX_DEALS,
	)


def _history(since) -> list[dict]:
	"""What the caller did at their customers lately, with what they wrote about it.

	The caller's own plan rows, so it is read by parent rather than through a
	permission query: a plan belongs to exactly one user.
	"""
	monday, _sunday = week_of(since)
	plans = frappe.get_all(
		"CRM Rep Plan",
		filters={"user": frappe.session.user, "week_start": (">=", monday)},
		pluck="name",
	)
	if not plans:
		return []
	rows = frappe.get_all(
		"CRM Rep Plan Item",
		filters={
			"parent": ("in", plans),
			"parenttype": "CRM Rep Plan",
			"planned_date": (">=", since),
			"status": ("in", ("Done", "Cancelled", "Missed")),
			"organization": ("is", "set"),
		},
		fields=["name", *ITEM_FIELDS],
		order_by="planned_date desc",
		limit=MAX_HISTORY,
	)
	for row in rows:
		row["outcome"] = _clip(row.get("outcome"))
	return rows


def _notes(since) -> list[dict]:
	rows = frappe.get_list(
		"FCRM Note",
		filters={"reference_doctype": ("in", NOTE_DOCTYPES), "modified": (">=", since)},
		fields=["name", "title", "content", "reference_doctype", "reference_docname", "owner", "modified"],
		order_by="modified desc",
		limit=MAX_NOTES,
	)
	for row in rows:
		# a rich-text field: the phone shows it as text, so it never has to
		# trust markup it stored days ago
		row["content"] = _clip(frappe.utils.strip_html(row.get("content") or ""))
	return rows


def _tasks() -> list[dict]:
	rows = frappe.get_list(
		"CRM Task",
		filters={"assigned_to": frappe.session.user, "status": ("in", OPEN_TASK_STATUSES)},
		fields=[
			"name",
			"title",
			"priority",
			"status",
			"due_date",
			"description",
			"reference_doctype",
			"reference_docname",
		],
		order_by="due_date asc",
		limit=MAX_TASKS,
	)
	for row in rows:
		row["description"] = _clip(frappe.utils.strip_html(row.get("description") or ""))
	return rows


def _clip(text: str | None) -> str:
	text = (text or "").strip()
	return text if len(text) <= TEXT_LIMIT else text[: TEXT_LIMIT - 1].rstrip() + "…"


def _stamp(moment) -> str:
	"""A site-clock datetime as text the phone can compare with its own."""
	return moment.strftime("%Y-%m-%d %H:%M:%S")
