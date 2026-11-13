# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Field mode: what a rep's phone carries to a site with no reception.

Two reads, and one write.

:func:`replay` is the write: it applies one entry from the phone's outbox --
a visit logged, an outcome, a note, a task -- exactly once, however many
times the phone sends it. See the function for the rules.

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
import math
import re
import time
from datetime import UTC, datetime, timedelta

import frappe
from frappe import _

from crm.api.rep_plan import (
	EDITABLE_ITEM_FIELDS,
	ITEM_FIELDS,
	LOGGABLE_TYPES,
	REFERENCE_DOCTYPES,
	_customer_available,
	cancel_item,
	complete_item,
	get_plan,
	log_activity,
	past_days_locked,
	save_plan,
)
from crm.fcrm.doctype.crm_offline_receipt.crm_offline_receipt import RECEIPT_DAYS
from crm.rep_planning import ACTIVITY_TYPES, EVENT_KINDS, MATCH_HORIZON_WEEKS, week_of
from crm.utils import is_sales_user, sales_user_only, user_rate_limited

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

# --- replay ---------------------------------------------------------------------------

RECEIPT = "CRM Offline Receipt"

# With "plan only for today or later" on, an activity is logged on the day it
# happens. A phone with no signal cannot, so one captured offline is accepted
# this long after the fact -- and flagged. Past it, the lock stands.
OFFLINE_GRACE_HOURS = 72

# An entry that took longer than this to arrive was captured without a
# connection, and its time is the device's word. Shorter is just a slow line.
LATE_AFTER_SECONDS = 15 * 60

# A device clock a little ahead of the server is a device clock, not a visit
# from the future.
CLOCK_TOLERANCE_SECONDS = 5 * 60

# A flush after a week away is a few dozen entries sent one after another.
REPLAY_RATE_SCOPE = "offline_replay"
REPLAY_RATE_LIMIT = 240

MAX_PAYLOAD_BYTES = 20_000
MAX_KNOWN_SECTIONS = 32
HASH_LENGTH = 64
NOTE_TEXT_LIMIT = 5000
TITLE_LIMIT = 140
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{15,63}$")

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


class NotAFieldUser(frappe.PermissionError):
	"""The caller has no sales role, so there is no pack for them -- any more, or ever.

	Its own name because the name is what reaches the phone (``exc_type``),
	and the phone acts on it: a pack already there is deleted at once. A plain
	``PermissionError`` must not do that. One raised from *inside* the pack --
	a list that stopped being readable because someone edited a role -- is a
	fault to fix on the server, and would otherwise empty every rep's phone
	on its next sync.
	"""


@frappe.whitelist()
def get_pack(known_hash: str | None = None, known_sections: dict | str | None = None) -> dict:
	"""Everything the caller's phone needs to work a site visit offline.

	Pass the ``hash`` of the pack already held to be told ``unchanged`` instead
	of being sent the same rows again.

	Pass its ``sections`` too -- the hash of each list, as the last answer gave
	them -- and a list that has not changed is named in ``kept`` instead of
	being sent. Everything a rep does on the phone changes the pack, so the
	whole-pack hash alone meant one note cost a download of every customer,
	contact and deal. A list is left out only when its hash here equals the
	one the phone says it holds: the phone gets exactly the rows it would have
	been sent, from its own copy. The rows are still read to know that; this
	saves the line, not the queries.
	"""
	# sales_user_only's test, with an answer of its own: see NotAFieldUser
	if not is_sales_user():
		frappe.throw(
			_("You are not permitted to access this resource."),
			NotAFieldUser,
			title=_("Not Allowed"),
		)
	body = _pack_body()
	sections = {key: _digest(rows) for key, rows in body.items()}
	digest = _digest(sections)

	envelope = {
		"user": frappe.session.user,
		"hash": digest,
		"sections": sections,
		"generated_at": _stamp(frappe.utils.now_datetime()),
		"today": str(frappe.utils.getdate()),
		"max_age_days": PACK_MAX_AGE_DAYS,
	}
	if known_hash and known_hash == digest:
		return {**envelope, "unchanged": True}
	held = _held_sections(known_sections)
	kept = sorted(key for key in body if held.get(key) == sections[key])
	return {
		**envelope,
		"unchanged": False,
		"kept": kept,
		**{key: rows for key, rows in body.items() if key not in kept},
	}


def _digest(value) -> str:
	return hashlib.sha256(
		json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
	).hexdigest()


def _held_sections(known_sections) -> dict[str, str]:
	"""The list hashes a phone says it holds, as text and nothing else.

	Anything unreadable is "holds nothing", which costs that phone a full
	download and no one anything else.
	"""
	if isinstance(known_sections, str):
		if len(known_sections) > MAX_PAYLOAD_BYTES:
			return {}
		try:
			known_sections = json.loads(known_sections or "{}")
		except (ValueError, RecursionError):
			return {}
	# the pack has ten lists and a hash is 64 characters: a claim far past
	# that is not a pack's, whichever way it was sent
	if not isinstance(known_sections, dict) or len(known_sections) > MAX_KNOWN_SECTIONS:
		return {}
	return {
		key: value
		for key, value in known_sections.items()
		if isinstance(key, str)
		and len(key) <= HASH_LENGTH
		and isinstance(value, str)
		and len(value) <= HASH_LENGTH
	}


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
			"offline_grace_hours": OFFLINE_GRACE_HOURS,
			"plannable_types": [kind for kind in ACTIVITY_TYPES if kind != "Unplanned Meeting"],
		},
		"plans": _plans(today),
		"sheets": _sheets(),
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


def _sheets() -> list[dict]:
	"""The reference sheets, by name and page: what a rep may keep on the phone.

	Only the list travels in the pack. The page images are fetched by the
	phone for the sheets the rep chooses to keep, through the ordinary file
	URLs and their ordinary permission check.
	"""
	from crm.api.reference import list_sheets

	try:
		rows = list_sheets()["sheets"]
	except frappe.PermissionError:
		return []
	return [
		{
			"name": row["name"],
			"title": row["title"],
			"note": row.get("note") or "",
			"modified": str(row["modified"]),
			"pages": [
				{
					"page": page.get("page"),
					"image": page.get("image"),
					"width": page.get("width"),
					"height": page.get("height"),
				}
				for page in row.get("pages") or []
				if isinstance(page, dict) and page.get("image")
			],
		}
		for row in rows
		# The switch an administrator uses to withdraw a sheet -- one with an
		# error in it, say. Everywhere else a rep meets sheet content honours
		# it; a copy kept on a phone must not be the way round.
		if row.get("available_to_assistant")
	]


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


# --- replay ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
@sales_user_only
def replay(
	request_id: str,
	action: str,
	payload: dict | str | None = None,
	captured_at: int | float | str | None = None,
) -> dict:
	"""Apply one entry from a device's outbox, exactly once.

	``request_id`` is chosen by the device when the entry is captured and sent
	with every attempt. The receipt row carrying it is inserted in the same
	transaction as the work, so there are only two outcomes: both are stored,
	or the action refused and neither is. A second copy -- the phone lost the
	answer and sent it again, or two tabs flushed at once -- finds the receipt,
	or loses the race for its primary key, and is told ``duplicate``.

	``captured_at`` is when the rep did it, in ms since the epoch, by the
	device's clock corrected for the skew the last handshake measured. It is
	never trusted to be in the future, and it only earns a rep anything -- a
	way past "activities are logged on the day they happen" -- inside
	``OFFLINE_GRACE_HOURS``, with the row flagged ``captured_offline``. Nor is
	an entry taken that is older than the receipts are kept (``RECEIPT_DAYS``):
	by then the receipt that would have called it a duplicate may be gone.

	The action is one of ``ACTIONS`` and nothing else: this is not a generic
	method dispatcher. Each handler does its own permission check as the
	session user, exactly as the endpoint it stands in for.
	"""
	if user_rate_limited(REPLAY_RATE_SCOPE, REPLAY_RATE_LIMIT):
		frappe.throw(_("Too many requests. Try again shortly."), frappe.TooManyRequestsError)

	request_id = frappe.utils.cstr(request_id).strip()
	if not _REQUEST_ID.match(request_id):
		frappe.throw(_("That entry has no usable id."), frappe.ValidationError)
	handler = ACTIONS.get(frappe.utils.cstr(action))
	if not handler:
		frappe.throw(_("That cannot be done offline."), frappe.ValidationError)
	payload = _payload(payload)
	moment, late, age = _captured(captured_at)

	if _already_applied(request_id):
		return {"request_id": request_id, "status": "duplicate"}
	if age > RECEIPT_DAYS * 86400:
		# Asked after the receipt, not before: one that is still there is the
		# better answer. Without one, an entry this old may be the retry of
		# something applied and since forgotten -- a phone that lost the answer
		# and then spent three months in a drawer -- and applying it would
		# write the note or the task a second time. A receipt is never older
		# than the capture it records, so inside this window it still exists.
		frappe.throw(
			_(
				"This was captured more than {0} days ago and can no longer be sent. "
				"Check whether it is already there, and write it again if it is not."
			).format(RECEIPT_DAYS),
			frappe.ValidationError,
		)

	frappe.db.savepoint("offline_replay")
	try:
		frappe.get_doc(
			{
				"doctype": RECEIPT,
				"request_id": request_id,
				"user": frappe.session.user,
				"action": action,
				"captured_at": moment,
				"late": 1 if late else 0,
			}
		).insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# the other copy of this entry got there between the check and the insert
		frappe.db.rollback(save_point="offline_replay")
		# a locking read: the plain one would see this transaction's snapshot,
		# taken before the other copy committed, and find no receipt to check
		_already_applied(request_id, current=True)
		return {"request_id": request_id, "status": "duplicate"}

	handler(payload, moment, late)
	return {"request_id": request_id, "status": "applied", "late": late}


def _already_applied(request_id: str, current: bool = False) -> bool:
	if current:
		# A shared lock, not FOR UPDATE: the failed insert left this
		# transaction a shared lock on the row already, and so did any third
		# copy of the entry. Each asking for an exclusive one is a deadlock.
		rows = frappe.db.sql(
			"select `user` from `tabCRM Offline Receipt` where name = %s lock in share mode",
			(request_id,),
		)
		owner = rows[0][0] if rows else None
	else:
		owner = frappe.db.get_value(RECEIPT, request_id, "user")
	if not owner:
		return False
	if owner != frappe.session.user:
		# Someone else's id. Not a duplicate, and not something to describe.
		frappe.throw(_("That entry has no usable id."), frappe.ValidationError)
	return True


def _payload(payload) -> dict:
	if isinstance(payload, str):
		if len(payload.encode()) > MAX_PAYLOAD_BYTES:
			frappe.throw(_("That entry is too large to send."), frappe.ValidationError)
		try:
			payload = json.loads(payload or "{}")
		except (ValueError, RecursionError):
			# RecursionError: a few kilobytes of nothing but "[[[[" is valid
			# JSON to start reading and a 500 to finish
			payload = None
	if not isinstance(payload, dict):
		frappe.throw(_("That entry could not be read."), frappe.ValidationError)
	if len(json.dumps(payload, default=str).encode()) > MAX_PAYLOAD_BYTES:
		frappe.throw(_("That entry is too large to send."), frappe.ValidationError)
	return payload


def _captured(captured_at) -> tuple[datetime, bool, float]:
	"""When the entry was captured, on the site's clock; whether it arrived late; its age in seconds."""
	now = time.time()
	try:
		captured = float(captured_at) / 1000 if captured_at not in (None, "") else now
	except (TypeError, ValueError):
		frappe.throw(_("That entry has no usable time."), frappe.ValidationError)
	if not math.isfinite(captured):
		# float("nan") parses, compares false with everything, and would get
		# as far as fromtimestamp before failing as a server error
		frappe.throw(_("That entry has no usable time."), frappe.ValidationError)
	if captured > now + CLOCK_TOLERANCE_SECONDS or captured <= 0:
		frappe.throw(_("That entry is dated in the future. Check the date on this device."))
	captured = min(captured, now)
	moment = frappe.utils.convert_utc_to_system_timezone(datetime.fromtimestamp(captured, tz=UTC))
	age = now - captured
	return moment.replace(tzinfo=None, microsecond=0), age > LATE_AFTER_SECONDS, age


def _name(payload: dict, key: str) -> str:
	"""A record name from the payload, as text and nothing else.

	The payload is JSON, so a value can arrive as a dict or a list -- and
	``frappe.db.exists`` and ``get_value`` read a dict as *filters*, with no row
	scoping. Handed one, a handler would answer "is there a task of Thabo's
	whose title starts with Impala" by which error it raised. Every name a
	handler looks up comes through here.
	"""
	value = payload.get(key)
	if value is None:
		return ""
	if not isinstance(value, str | int):
		frappe.throw(_("That entry could not be read."), frappe.ValidationError)
	return frappe.utils.cstr(value).strip()


def _text(value, limit: int) -> str:
	if value is not None and not isinstance(value, str | int | float):
		frappe.throw(_("That entry could not be read."), frappe.ValidationError)
	text = frappe.utils.cstr(value).strip()
	if len(text) > limit:
		frappe.throw(_("That is too long. Keep it under {0} characters.").format(limit))
	return text


def _as_html(text: str) -> str:
	"""Plain text typed on a phone, as the rich-text fields store it."""
	return frappe.utils.escape_html(text).replace("\n", "<br>")


def _flag_offline(item: str, moment: datetime, late: bool) -> None:
	"""Mark an outcome whose time is the device's word, not the server's.

	Late, or dated on an earlier day than the one it arrived on -- captured at
	23:52 and delivered at 00:03 is eleven minutes old and already yesterday's.
	The same test ``_replay_log_activity`` applies.
	"""
	if late or moment.date() < frappe.utils.getdate():
		frappe.db.set_value("CRM Rep Plan Item", item, "captured_offline", 1)


def _customer(name: str) -> str | None:
	"""A customer the caller may log or plan against, or the refusal ``_readable`` gives.

	Asked with the predicate the plan's own save uses, and asked first: left to
	the code behind it, a customer that does not exist and one that is another
	rep's were refused in different words.
	"""
	if not name:
		return None
	if not _customer_available(name):
		frappe.throw(_("That record is no longer available."), frappe.PermissionError)
	return name


def _own_item(item: str) -> str:
	"""The week a planned item of the caller's own is in, or one refusal for gone and not yours."""
	row = (
		frappe.db.get_value("CRM Rep Plan Item", item, ["parent", "parenttype"], as_dict=True)
		if item
		else None
	)
	plan = (
		frappe.db.get_value("CRM Rep Plan", row.parent, ["user", "week_start"], as_dict=True)
		if row and row.parenttype == "CRM Rep Plan"
		else None
	)
	if not plan or plan.user != frappe.session.user:
		frappe.throw(_("That activity is no longer available."), frappe.PermissionError)
	return plan.week_start


def _replay_log_activity(payload: dict, moment: datetime, late: bool) -> None:
	# On an earlier day than today, by the site's calendar. Asked of the date,
	# not of `late`: a visit captured at 23:52 and delivered at 00:03 is eleven
	# minutes old and already "yesterday", and without this the day lock
	# refused it for good.
	past = moment.date() < frappe.utils.getdate()
	if (
		past
		and past_days_locked()
		and frappe.utils.now_datetime() - moment > timedelta(hours=OFFLINE_GRACE_HOURS)
	):
		frappe.throw(
			_(
				"This was captured more than {0} hours ago. Activities are logged on the day they happen."
			).format(OFFLINE_GRACE_HOURS),
			frappe.ValidationError,
		)
	log_activity(
		organization=_customer(_name(payload, "organization")),
		note=_text(payload.get("note"), NOTE_TEXT_LIMIT),
		when=moment,
		reference_doctype=_name(payload, "reference_doctype") or None,
		reference_docname=_name(payload, "reference_docname") or None,
		activity_type=_name(payload, "activity_type") or "Unplanned Meeting",
		# flagged whenever the server did not witness the day it is dated
		captured_offline=late or past,
	)


def _replay_complete_item(payload: dict, moment: datetime, late: bool) -> None:
	item = _name(payload, "item")
	week_start = _own_item(item)
	# complete_item wants a time inside the item's own week. A Friday visit
	# closed on Monday falls outside it, and then the planned day stands, as it
	# does when the Planner is given no time at all.
	start, end = week_of(frappe.utils.getdate(week_start))
	when = str(moment) if start <= moment.date() <= end else None
	complete_item(item, _text(payload.get("outcome"), NOTE_TEXT_LIMIT), when)
	_flag_offline(item, moment, late)


def _replay_cancel_item(payload: dict, moment: datetime, late: bool) -> None:
	item = _name(payload, "item")
	_own_item(item)
	cancel_item(item, _text(payload.get("reason"), NOTE_TEXT_LIMIT))
	_flag_offline(item, moment, late)


def _replay_plan_item(payload: dict, moment: datetime, late: bool) -> None:
	"""Add one planned activity to the caller's week.

	The Planner saves a whole week at a time, guarded by "nobody changed it
	since you loaded it". A phone that was offline for two days cannot make
	that promise, and losing the week to a conflict is the wrong price for
	adding one visit. So offline planning only ever *adds*: the week as the
	server holds it now, plus this row, through ``save_plan`` -- which applies
	every rule the Planner's own save does (the horizon, the day lock, the
	customer's owner).
	"""
	planned_date = _name(payload, "planned_date")[:10]
	if not planned_date:
		# getdate("") is today: a missing day must not quietly become one
		frappe.throw(_("Choose the day."), frappe.ValidationError)
	try:
		day = frappe.utils.getdate(planned_date)
	except Exception:
		frappe.throw(_("That date could not be read."), frappe.ValidationError)
	activity_type = _name(payload, "activity_type")
	if activity_type not in ACTIVITY_TYPES or activity_type == "Unplanned Meeting":
		frappe.throw(_("{0} cannot be planned.").format(activity_type or _("That")), frappe.ValidationError)
	if day < moment.date():
		# planned for a day that had already passed when the rep planned it
		frappe.throw(_("Activities are planned for today or later."), frappe.ValidationError)

	# save_plan drops a customer that no longer exists and keeps the row, and
	# refuses one that is another rep's. Neither is what the rep planned, and
	# the difference is not theirs to learn: one refusal for both.
	organization = _customer(_name(payload, "organization"))
	if activity_type in EVENT_KINDS and not organization:
		frappe.throw(_("Choose the customer for this {0}.").format(_(activity_type)), frappe.ValidationError)

	monday, _sunday = week_of(day)
	row = {
		"activity_type": activity_type,
		"planned_date": str(day),
		"note": _text(payload.get("note"), TITLE_LIMIT),
		"organization": organization,
	}
	current = get_plan(str(monday))
	kept = [
		{"name": item["name"], **{f: item.get(f) for f in EDITABLE_ITEM_FIELDS}} for item in current["items"]
	]
	# With the week's own timestamp, as the Planner sends it. If the week
	# changed between the read and the write -- a row deleted on the desktop
	# in that instant -- writing back what was read would put the row back,
	# so that is refused (TimestampMismatchError). There is no point reading
	# again here: this transaction goes on seeing the week as it was when it
	# began. The phone treats that refusal as "try again", and its next
	# request is a new transaction that sees the week as it is.
	save_plan(str(monday), [*kept, row], str(current["modified"] or ""))


def _readable(doctype: str, name: str, allowed: tuple[str, ...]) -> tuple[str, str]:
	"""A record the caller may attach something to, or a refusal that names nothing.

	One exception for "no such record" and "not yours": two would tell a rep
	which customer names exist outside their own book.
	"""
	if (
		doctype not in allowed
		or not name
		or not frappe.db.exists(doctype, name)
		or not frappe.has_permission(doctype, "read", name)
	):
		frappe.throw(_("That record is no longer available."), frappe.PermissionError)
	return doctype, name


def _replay_add_note(payload: dict, moment: datetime, late: bool) -> None:
	doctype, name = _readable(
		_name(payload, "reference_doctype"),
		_name(payload, "reference_docname"),
		NOTE_DOCTYPES,
	)
	content = _text(payload.get("content"), NOTE_TEXT_LIMIT)
	if not content:
		frappe.throw(_("Write the note first."), frappe.ValidationError)
	title = _text(payload.get("title"), TITLE_LIMIT) or content.splitlines()[0][:TITLE_LIMIT]
	frappe.get_doc(
		{
			"doctype": "FCRM Note",
			"title": title,
			"content": _as_html(content),
			"reference_doctype": doctype,
			"reference_docname": name,
		}
	).insert()


def _replay_create_task(payload: dict, moment: datetime, late: bool) -> None:
	title = _text(payload.get("title"), TITLE_LIMIT)
	if not title:
		frappe.throw(_("Give the task a title."), frappe.ValidationError)
	task = {
		"doctype": "CRM Task",
		"title": title,
		"status": "Todo",
		"assigned_to": frappe.session.user,
		"description": _as_html(_text(payload.get("description"), NOTE_TEXT_LIMIT)),
	}
	if payload.get("due_date"):
		try:
			due = frappe.utils.getdate(_name(payload, "due_date")[:10])
		except Exception:
			frappe.throw(_("That due date could not be read."), frappe.ValidationError)
		task["due_date"] = datetime.combine(due, datetime.min.time()).replace(hour=9)
	if payload.get("reference_docname"):
		task["reference_doctype"], task["reference_docname"] = _readable(
			_name(payload, "reference_doctype"),
			_name(payload, "reference_docname"),
			REFERENCE_DOCTYPES,
		)
	frappe.get_doc(task).insert()


def _replay_close_task(payload: dict, moment: datetime, late: bool) -> None:
	name = _name(payload, "task")
	task = frappe.get_doc("CRM Task", name) if name and frappe.db.exists("CRM Task", name) else None
	# The pack only ever offered the caller their own tasks. Missing and not
	# yours get the same answer, for the reason _readable gives.
	if not task or task.assigned_to != frappe.session.user or not task.has_permission("write"):
		frappe.throw(_("That task is no longer available."), frappe.PermissionError)
	if task.status == "Done":
		frappe.throw(_("This task is already done."), frappe.ValidationError)
	note = _text(payload.get("closing_note"), NOTE_TEXT_LIMIT)
	if not note:
		frappe.throw(_("Say how it was finished."), frappe.ValidationError)
	task.status = "Done"
	task.closing_note = note
	task.save()


ACTIONS = {
	"log_activity": _replay_log_activity,
	"complete_item": _replay_complete_item,
	"cancel_item": _replay_cancel_item,
	"add_note": _replay_add_note,
	"create_task": _replay_create_task,
	"close_task": _replay_close_task,
	"plan_item": _replay_plan_item,
}
