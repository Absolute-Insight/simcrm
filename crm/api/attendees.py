"""Attendees typed onto an event by their address.

The calendar used to give such an attendee a Contact from the browser: it asked
for one with that address among the Contacts the rep can read, and created one
when there was none. A Contact at another rep's customer is not among them, so
the rep's meeting with that person made a second Contact for them and split the
customer's history in two. Telling the browser about the hidden Contact instead
would tell the rep whose customer the address belongs to.

So the event's own save resolves the address, here, against every Contact:

- one both the rep and the event's owner can read is put on the participant row,
  as a picked Contact would be;
- otherwise the row keeps only the typed address, and the Contact behind it --
  an existing one the rep may not read, or one created for the rep when there is
  none -- is recorded in ``CRM Event Attendee``, which reps cannot read at all.

The hidden case and the not-found case leave the rep with the same row and the
same response. They are told apart by nothing on the event: not the participant
row, its version history, a list filter on it, or a timeline Communication
(frappe makes one per named participant; a typed one is never named). Storing
the hidden Contact's name on the row and blanking it on the way out, as call
logs do, was not enough here: the row belongs to an event the rep owns, so
frappe's generic list API lets them filter their own events on it character by
character.

Two saves adding the same new address at once must not create two Contacts, so
the lookup and the insert run under a named database lock per address, held to
the end of the transaction, and the lookup also reads through a fresh
connection: the request's own snapshot predates the other save's commit.
"""

from __future__ import annotations

import hashlib

import frappe
from frappe import _

DOCTYPE = "CRM Event Attendee"
LOCK_TIMEOUT = 10  # seconds
LOCK_PREFIX = "crm-attendee-"


def normalize_email(email) -> str:
	return (email or "").strip().lower()


def _is_typed(row) -> bool:
	"""A Contact row with an address and no Contact named."""
	return (
		(row.get("reference_doctype") or "Contact") == "Contact"
		and not row.get("reference_docname")
		and bool(normalize_email(row.get("email")))
	)


def resolve_event_attendees(doc, method=None) -> None:
	"""Event before_validate: give each typed attendee its Contact."""
	rows = doc.get("event_participants") or []
	for row in rows:
		# set on every row, every save: nothing the request carried survives
		row._crm_typed_attendee = False
	typed = [row for row in rows if _is_typed(row)]
	doc.flags.crm_attendees = {}
	if not typed:
		return
	if frappe.session.user == "Guest":
		return

	users = {frappe.session.user, _event_owner(doc)}
	linked = {}
	if not doc.is_new():
		linked = {
			r.email: r.contact
			for r in frappe.get_all(DOCTYPE, filters={"event": doc.name}, fields=["email", "contact"])
		}

	wanted = sorted({normalize_email(row.email) for row in typed} - set(linked))
	# sorted, so two saves locking overlapping addresses take them in one order
	for key in wanted:
		_lock(key)
	found = _contacts_by_email(wanted)

	# an address already resolved for this event stays as it was: re-deciding it
	# on a later save would answer differently once the rep's own Contact exists
	choices: dict[str, tuple[str, str | None]] = {key: ("kept", contact) for key, contact in linked.items()}
	for key in wanted:
		candidates = found.get(key, [])
		readable = next(
			(
				c
				for c in candidates
				# in this transaction's snapshot too: one another save committed
				# since is recorded apart, where its link is not re-checked
				if frappe.db.exists("Contact", c) and all(_contact_visible(c, u) for u in users)
			),
			None,
		)
		if readable:
			choices[key] = ("named", readable)
		else:
			choices[key] = ("kept", candidates[0] if candidates else None)

	for row in typed:
		key = normalize_email(row.email)
		row.email = row.email.strip()
		row.reference_doctype = "Contact"
		how, contact = choices[key]
		if how == "named":
			row.reference_docname = contact
			continue
		if not contact:
			contact = _create_contact(row.email, doc)
			choices[key] = ("kept", contact)
		row._crm_typed_attendee = True
		doc.flags.crm_attendees[key] = contact


def sync_event_attendees(doc, method=None) -> None:
	"""Event on_update: the attendee rows are what this save resolved."""
	wanted = doc.flags.get("crm_attendees")
	if wanted is None:
		return
	stored = {
		r.email: r for r in frappe.get_all(DOCTYPE, filters={"event": doc.name}, fields=["name", "email"])
	}
	for key, contact in wanted.items():
		if key in stored:
			continue
		attendee = frappe.get_doc({"doctype": DOCTYPE, "event": doc.name, "email": key, "contact": contact})
		# a Contact found through the fresh connection is not in this snapshot yet
		attendee.flags.ignore_links = True
		attendee.insert(ignore_permissions=True)
	gone = [r.name for key, r in stored.items() if key not in wanted]
	if gone:
		frappe.db.delete(DOCTYPE, {"name": ("in", gone)})


def drop_event_attendees(doc, method=None) -> None:
	"""Event on_trash."""
	frappe.db.delete(DOCTYPE, {"event": doc.name})


def drop_contact_attendees(doc, method=None) -> None:
	"""Contact on_trash: the event keeps the typed address, and its next save
	finds the person again."""
	frappe.db.delete(DOCTYPE, {"contact": doc.name})


@frappe.whitelist()
def get_contact_events(contact: str) -> list[dict]:
	"""The events a Contact attends, by participant row or typed address, among
	the events the caller can read. For the Contact's own readers only."""
	if (
		not contact
		or not frappe.db.exists("Contact", contact)
		or not frappe.has_permission("Contact", "read", doc=contact)
	):
		# one answer for "no such contact" and "not yours": the name is the question
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	names = set(
		frappe.get_all(
			"Event Participants",
			filters={"parenttype": "Event", "reference_doctype": "Contact", "reference_docname": contact},
			pluck="parent",
		)
	)
	names |= set(frappe.get_all(DOCTYPE, filters={"contact": contact}, pluck="event"))
	if not names:
		return []
	return frappe.get_list(
		"Event",
		filters={"name": ("in", sorted(names))},
		fields=["name", "subject", "starts_on", "ends_on", "status", "owner"],
		order_by="starts_on desc",
		limit_page_length=50,
	)


def _event_owner(doc) -> str:
	"""The stored owner: a request does not get to say whose event it is."""
	if doc.is_new():
		return frappe.session.user
	return frappe.db.get_value("Event", doc.name, "owner") or frappe.session.user


def _contact_visible(contact: str, user: str) -> bool:
	from crm.permissions.customers import contact_visible

	return contact_visible(contact, user)


def _create_contact(email: str, event) -> str:
	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": email.split("@")[0] or email,
			"email_ids": [{"email_id": email, "is_primary": 1}],
		}
	)
	contact.flags.ignore_permissions = bool(event.flags.ignore_permissions)
	contact.insert()
	return contact.name


_LOOKUP = """
	select lower(trim(c.email_id)) as k, c.name, c.creation, 1 as is_primary
	from `tabContact` c
	where lower(trim(c.email_id)) in %(keys)s
	union all
	select lower(trim(ce.email_id)) as k, c.name, c.creation, ce.is_primary
	from `tabContact Email` ce
	join `tabContact` c on c.name = ce.parent
	where ce.parenttype = 'Contact' and lower(trim(ce.email_id)) in %(keys)s
"""


def _contacts_by_email(keys: list[str]) -> dict[str, list[str]]:
	"""Per address, every Contact carrying it: the one it is primary on first,
	then the oldest. Read on this transaction (its own uncommitted Contacts) and
	on a fresh connection (another save's, committed after this one began)."""
	if not keys:
		return {}
	from crm.utils.autonomous import autonomous_db

	params = {"keys": tuple(keys)}
	rows = list(frappe.db.sql(_LOOKUP, params, as_dict=True))
	with autonomous_db() as db:
		rows += list(db.sql(_LOOKUP, params, as_dict=True))

	best: dict[tuple[str, str], tuple] = {}
	for row in rows:
		rank = (-int(row.is_primary or 0), row.creation, row.name)
		current = best.get((row.k, row.name))
		if current is None or rank < current:
			best[(row.k, row.name)] = rank
	out: dict[str, list[str]] = {}
	for (key, name), _rank in sorted(best.items(), key=lambda item: (item[0][0], item[1])):
		out.setdefault(key, []).append(name)
	return out


def _lock(key: str) -> None:
	"""A named lock on ``key``, held until this transaction commits or rolls back."""
	held = getattr(frappe.local, "crm_attendee_locks", None)
	if held is None:
		held = frappe.local.crm_attendee_locks = set()
	name = LOCK_PREFIX + hashlib.sha256(key.encode()).hexdigest()[:48]
	if name in held:
		return
	if not held:
		frappe.db.after_commit.add(_release_locks)
		frappe.db.after_rollback.add(_release_locks)
	got = frappe.db.sql("select get_lock(%s, %s)", (name, LOCK_TIMEOUT))[0][0]
	if got != 1:
		frappe.throw(_("This attendee is being added by another save. Save again in a moment."))
	held.add(name)


def _release_locks() -> None:
	held = getattr(frappe.local, "crm_attendee_locks", None)
	while held:
		frappe.db.sql("select release_lock(%s)", (held.pop(),))
