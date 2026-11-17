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
- otherwise the row keeps only the typed address, and ``CRM Event Attendee``,
  which reps cannot read at all, records the Contact behind it -- or none yet.
  Nothing is created when nobody has the address: a Contact made for the rep
  would be one they (and every rep) could list, and its absence in the other
  case would say whose customer the address is. A Contact saved later with the
  address is linked to the waiting rows then (:func:`link_waiting_attendees`).

The hidden case and the not-found case leave every rep with the same row, the
same response, the same Contacts and the same events. Nothing on the event tells
them apart: not the participant row, its version history, a list filter on it,
or a timeline Communication (frappe makes one per named participant; a typed one
is never named). Storing the hidden Contact's name on the row and blanking it on
the way out, as call logs do, was not enough here: the row belongs to an event
the rep owns, so frappe's generic list API lets them filter their own events on
it character by character.

An event save and a Contact save carrying the same address can run at once, so
both take a named database lock per address, held to the end of the
transaction, and the event's lookup also reads through a fresh connection: the
request's own snapshot predates the other save's commit. Otherwise a Contact
committed in between would leave the attendee waiting for good.
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

	# an address already resolved for this event stays as it was: naming a
	# Contact on the row now would change what the rep sees on a later save
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
		attendee = frappe.get_doc(
			{"doctype": DOCTYPE, "event": doc.name, "email": key, "contact": contact or None}
		)
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
	"""Contact on_trash: the attendee waits again for a Contact with its address."""
	frappe.db.set_value(DOCTYPE, {"contact": doc.name}, "contact", None, update_modified=False)


def link_waiting_attendees(doc, method=None) -> None:
	"""Contact on_update: an attendee typed before anyone had this address is
	this Contact. Recorded off the event only, so nothing the event's owner sees
	changes."""
	keys = sorted(_contact_keys(doc))
	if not keys:
		return
	for key in keys:
		_lock(key)
	Attendee = frappe.qb.DocType(DOCTYPE)
	# an UPDATE reads the latest committed rows, whatever this snapshot holds
	(
		frappe.qb.update(Attendee)
		.set(Attendee.contact, doc.name)
		.where(Attendee.email.isin(keys))
		.where(Attendee.contact.isnull() | (Attendee.contact == ""))
	).run()


def _contact_keys(contact) -> set[str]:
	keys = {normalize_email(row.email_id) for row in contact.get("email_ids") or []}
	keys.add(normalize_email(contact.get("email_id")))
	keys.discard("")
	return keys


def ensure_contact_email_index() -> None:
	"""after_migrate: frappe indexes ``tabContact.email_id`` but not the address
	rows, which every attendee lookup reads under its lock. Contact Email is
	frappe's table, so no doctype JSON of ours can ask for it; ``add_index`` does
	nothing when the index is already there."""
	frappe.db.add_index("Contact Email", ["email_id"])


def _event_owner(doc) -> str:
	"""The stored owner: a request does not get to say whose event it is."""
	if doc.is_new():
		return frappe.session.user
	return frappe.db.get_value("Event", doc.name, "owner") or frappe.session.user


def _contact_visible(contact: str, user: str) -> bool:
	from crm.permissions.customers import contact_visible

	return contact_visible(contact, user)


# On the indexed columns as stored: the tables' collation (utf8mb4_unicode_ci)
# already matches without regard to case or trailing spaces. An address stored
# with a leading space is not found, and waits as one nobody has.
_LOOKUP = """
	select lower(trim(c.email_id)) as k, c.name, c.creation, 1 as is_primary
	from `tabContact` c
	where c.email_id in %(keys)s
	union all
	select lower(trim(ce.email_id)) as k, c.name, c.creation, ce.is_primary
	from `tabContact Email` ce
	join `tabContact` c on c.name = ce.parent
	where ce.email_id in %(keys)s and ce.parenttype = 'Contact'
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
