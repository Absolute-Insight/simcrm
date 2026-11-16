# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The ERP write ledger: one row per write the CRM sends the ERP that carries no key
of its own, and what came of it.

A Customer under AutoNumber, a SalesOrder: each is a PUT with no key in the body, so
sending it twice makes two records in the client's ERP. A write whose answer never
came may still have landed, so it leaves its row OPEN (In Flight, then Unknown) and
the next attempt looks for what that one made before it sends anything. The row is
closed -- Applied, Refused, Abandoned -- once the outcome is on record.

Why a table and not the cache redis, where this used to live: a flush, an eviction
or a restart forgot the guard, and the next click sent a second order. Why not the
request's own transaction: the request that never heard back is exactly the one that
is rolled back, or killed. So every read and write here goes through a connection of
its own (crm.utils.autonomous) that commits at once -- and ONLY through it: see that
module for why.

``open_key`` holds the target while the row is open and is NULL once it is closed;
its UNIQUE index is what makes "at most one open write per target" true across
workers. A closed row keeps its history (an audit trail), and a new write to the same
target opens a new row.
"""

import json

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, now_datetime

from crm.utils.autonomous import autonomous_db, is_duplicate

DOCTYPE = "CRM ERP Write"
TABLE = f"`tab{DOCTYPE}`"

IN_FLIGHT = "In Flight"
UNKNOWN = "Unknown"
APPLIED = "Applied"
REFUSED = "Refused"
ABANDONED = "Abandoned"
OPEN_STATES = (IN_FLIGHT, UNKNOWN)
CLOSED_STATES = (APPLIED, REFUSED, ABANDONED)

# what each kind's reference is a name of
REFERENCE_DOCTYPES = {
	"Customer": "CRM Organization",
	"CustomerContact": "CRM Organization",
	"SalesOrder": "CRM Deal",
}

# closed rows older than this are purged; an open row never is
KEEP_CLOSED_DAYS = 180
_ERROR_LENGTH = 1000


class CRMERPWrite(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attempts: DF.Int
		error: DF.SmallText | None
		finished_at: DF.Datetime | None
		kind: DF.Literal["Customer", "CustomerContact", "SalesOrder"]
		marker: DF.Code | None
		open_key: DF.Data | None
		reference_doctype: DF.Link | None
		reference_name: DF.Data | None
		remote_id: DF.Data | None
		started_at: DF.Datetime | None
		state: DF.Literal["In Flight", "Unknown", "Applied", "Refused", "Abandoned"]
		target: DF.Data
		triggered_by: DF.Data | None
	# end: auto-generated types

	pass


def target_key(kind: str, reference: str) -> str:
	return f"{kind}::{reference}"


def _split(target: str) -> tuple[str, str]:
	kind, _sep, reference = target.partition("::")
	return kind, reference


def _dump(marker) -> str | None:
	return None if marker is None else json.dumps(marker, sort_keys=True, default=str)


def _load(raw):
	if not raw:
		return None
	try:
		return json.loads(raw)
	except ValueError:
		return None


def _short(error) -> str | None:
	return None if error is None else str(error)[:_ERROR_LENGTH]


def _user() -> str:
	return getattr(getattr(frappe.local, "session", None), "user", None) or "Administrator"


def _open_row(db, target: str):
	rows = db.sql(
		f"select name, target, state, attempts, marker, remote_id, error, started_at from {TABLE}"
		" where open_key = %s",
		(target,),
		as_dict=True,
	)
	if not rows:
		return None
	row = rows[0]
	row.marker = _load(row.marker)
	return row


def open_write(target: str):
	"""The open row for ``target`` -- name, state, attempts, marker (parsed), remote_id,
	error, started_at -- or None. Raises when the database cannot be asked: "no answer" is
	not "no write in flight"."""
	with autonomous_db() as db:
		return _open_row(db, target)


def _insert(db, target: str, marker, state: str = IN_FLIGHT) -> str:
	kind, reference = _split(target)
	now = now_datetime()
	name = frappe.generate_hash(length=12)
	db.sql(
		f"""insert into {TABLE}
			(name, creation, modified, owner, modified_by, docstatus, idx,
			target, open_key, kind, reference_doctype, reference_name, state,
			attempts, started_at, triggered_by, marker)
		values (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s)""",
		(
			name,
			now,
			now,
			_user(),
			_user(),
			target,
			target,
			kind,
			REFERENCE_DOCTYPES.get(kind),
			reference,
			state,
			now,
			_user(),
			_dump(marker),
		),
	)
	return name


def acquire(target: str, marker, expected=None) -> str | None:
	"""Open the write to ``target`` before it is sent; the row's name, or None when
	another attempt holds it.

	With no ``expected`` row, an insert: the UNIQUE ``open_key`` refuses it if any
	other worker opened one first, however close together they ran. With one (a retry
	of a write that never heard back, after looking for what it made), that row is
	taken over only if it is still exactly the attempt the caller read -- a compare-
	and-set on its attempt count, so two retries cannot both send."""
	with autonomous_db() as db:
		if expected is None:
			try:
				return _insert(db, target, marker)
			except Exception as e:
				if is_duplicate(db, e):
					return None
				raise
		now = now_datetime()
		db.sql(
			f"""update {TABLE}
			set state = %s, attempts = attempts + 1, marker = %s, started_at = %s,
				triggered_by = %s, error = null, finished_at = null, modified = %s, modified_by = %s
			where name = %s and open_key = %s and attempts = %s""",
			(IN_FLIGHT, _dump(marker), now, _user(), now, _user(), expected.name, target, expected.attempts),
		)
		return expected.name if db._cursor.rowcount == 1 else None


def put_marker(target: str, marker) -> str:
	"""Open ``target`` with ``marker``, or replace the marker of the row already open:
	for a follow-up that records what is still to do rather than guarding a send."""
	with autonomous_db() as db:
		try:
			return _insert(db, target, marker)
		except Exception as e:
			if not is_duplicate(db, e):
				raise
		now = now_datetime()
		db.sql(
			f"update {TABLE} set marker = %s, modified = %s, modified_by = %s where open_key = %s",
			(_dump(marker), now, _user(), target),
		)
		row = _open_row(db, target)
		return row.name if row else None


def record_unknown(target: str, error) -> None:
	"""The write got no answer: the row stays open, so the next attempt looks first."""
	with autonomous_db() as db:
		db.sql(
			f"update {TABLE} set state = %s, error = %s, modified = %s where open_key = %s",
			(UNKNOWN, _short(error), now_datetime(), target),
		)


def close(target: str, state: str, error=None, remote_id=None) -> None:
	"""Settle the open row for ``target``, if there is one."""
	assert state in CLOSED_STATES, state
	now = now_datetime()
	with autonomous_db() as db:
		db.sql(
			f"""update {TABLE}
			set state = %s, open_key = null, finished_at = %s, modified = %s,
				error = coalesce(%s, error), remote_id = coalesce(%s, remote_id)
			where open_key = %s""",
			(state, now, now, _short(error), None if remote_id is None else str(remote_id), target),
		)


def close_after_commit(target: str, state: str = APPLIED, remote_id=None) -> None:
	"""Settle the row once the request's own transaction commits -- and only then. A
	rollback after a write that landed (a worker killed before its commit) leaves the
	row open, so the next attempt finds the record instead of making another."""

	def settle():
		try:
			close(target, state, remote_id=remote_id)
		except Exception:
			# left open, the next attempt looks before it sends: safe, only slower
			frappe.log_error(frappe.get_traceback(), "ERP write ledger: could not settle a write")

	frappe.db.after_commit.add(settle)


def move(old_target: str, new_target: str) -> None:
	"""A rename of the record the target names: the open row follows it. When the new
	name already has one open, that one stands and the old one is abandoned -- one
	open write per target."""
	kind, reference = _split(new_target)
	now = now_datetime()
	with autonomous_db() as db:
		if not _open_row(db, old_target):
			return
		try:
			db.sql(
				f"""update {TABLE} set target = %s, open_key = %s, reference_name = %s, modified = %s
				where open_key = %s""",
				(new_target, new_target, reference, now, old_target),
			)
		except Exception as e:
			if not is_duplicate(db, e):
				raise
			db.sql(
				f"""update {TABLE} set state = %s, open_key = null, finished_at = %s, modified = %s,
					error = %s where open_key = %s""",
				(ABANDONED, now, now, _short(f"renamed onto {reference}, which had its own"), old_target),
			)


def purge_settled() -> None:
	"""Daily: drop closed rows past KEEP_CLOSED_DAYS. An open row is never dropped --
	it is the only thing between a retry and a second record in the client's ERP."""
	cutoff = add_days(now_datetime(), -KEEP_CLOSED_DAYS)
	with autonomous_db() as db:
		db.sql(
			f"""delete from {TABLE}
			where open_key is null and state in %s and coalesce(finished_at, modified) < %s""",
			(CLOSED_STATES, cutoff),
		)
