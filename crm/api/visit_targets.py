# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Visit targets: the rep list behind Settings -> Visit Targets, and the pro-ration.

A target is a number of customer visits per working week (``CRM Visit Target``).
Every other period is pro-rated by its working days, Monday to Friday, so a
month, a fortnight and a single week read against the same weekly number --
the same idea as quota's pro-ration by covered days, with the week as the unit.

Writing a target is a manager act, guarded exactly like quota: only managers,
only for their own subtree, and never their own row unless they administer the
site. The guards are quota's own (``crm.api.quota``), not a copy of them.
"""

from __future__ import annotations

import math
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cstr, getdate

from crm.api.quota import _is_manager, _not_the_caller, _only_own_team, _sales_users
from crm.utils import sales_user_only

DOCTYPE = "CRM Visit Target"

# far above any real week (MBP's managers talk about 15) and well inside the
# Int column, so a stray keystroke is refused rather than stored
MAX_VISITS_PER_WEEK = 200


def working_days(from_date, to_date) -> int:
	"""Monday-to-Friday days in the inclusive range; 0 for an inverted one."""
	start, end = getdate(from_date), getdate(to_date)
	if end < start:
		return 0
	span = (end - start).days + 1
	weeks, rest = divmod(span, 7)
	days = weeks * 5
	for offset in range(rest):
		if (start + timedelta(days=weeks * 7 + offset)).weekday() < 5:
			days += 1
	return days


def target_for(users, from_date, to_date) -> dict[str, float]:
	"""``{user: visits due in [from_date, to_date]}`` for each rep that has a target.

	visits_per_week x working days / 5, in one query. A rep with no row, or a
	row of 0 (the form's default), is left out: no target is not a target of
	nothing, and the callers report it as "No target" rather than as on track.
	"""
	users = sorted({u for u in users or [] if u})
	if not users:
		return {}
	days = working_days(from_date, to_date)
	rows = frappe.get_all(
		DOCTYPE,
		filters={"user": ("in", users), "visits_per_week": (">", 0)},
		fields=["user", "visits_per_week"],
	)
	return {row.user: row.visits_per_week * days / 5 for row in rows}


def _only_managers():
	if not _is_manager():
		frappe.throw(_("Only a Sales Manager can set visit targets."), frappe.PermissionError)


def _can_write(user: str) -> bool:
	"""What ``set_visit_target`` would allow, without raising -- for the grid."""
	if not _is_manager():
		return False
	return user != frappe.session.user or "System Manager" in frappe.get_roles()


@frappe.whitelist()
@sales_user_only
def get_visit_targets():
	"""One row per rep the caller may see: their weekly target and whether the
	caller may change it. A rep gets their own row, read-only."""
	from crm.api.rep_plan import get_visible_reps

	# the planner's rep picker: the same people whose plans the caller can open
	users = get_visible_reps()
	if not users:
		return []
	names = {
		u.name: u.full_name
		for u in frappe.get_all("User", filters={"name": ("in", users)}, fields=["name", "full_name"])
	}
	targets = dict(
		frappe.get_all(
			DOCTYPE, filters={"user": ("in", users)}, fields=["user", "visits_per_week"], as_list=True
		)
	)
	rows = [
		{
			"user": user,
			"full_name": names.get(user) or user,
			"visits_per_week": targets.get(user) or None,
			"editable": _can_write(user),
		}
		for user in users
	]
	rows.sort(key=lambda r: (r["full_name"] or r["user"]).lower())
	return rows


@frappe.whitelist()
@sales_user_only
def set_visit_target(user: str, visits_per_week: int | str | None = None):
	"""Create, update or (for 0 or blank) clear one rep's weekly visit target."""
	_only_managers()
	_only_own_team(user)
	_not_the_caller(user)
	if user not in _sales_users():
		frappe.throw(_("{0} is not a sales user.").format(user))

	raw = cstr(visits_per_week).strip()
	try:
		value = float(raw) if raw else 0.0
		if not math.isfinite(value):
			raise ValueError(raw)
	except ValueError:
		# flt() would read "abc" as 0, and 0 clears the target
		frappe.throw(_("A visit target is a whole number of visits."))
	if value < 0:
		frappe.throw(_("A visit target cannot be negative."))
	if value != int(value):
		frappe.throw(_("A visit target is a whole number of visits."))
	if value > MAX_VISITS_PER_WEEK:
		frappe.throw(_("A visit target is at most {0} a week.").format(MAX_VISITS_PER_WEEK))
	value = int(value)

	exists = frappe.db.exists(DOCTYPE, user)
	if not value:
		if exists:
			# through the document, so has_permission is asked as well as the role
			frappe.delete_doc(DOCTYPE, user)
		return {"user": user, "visits_per_week": None}

	if exists:
		doc = frappe.get_doc(DOCTYPE, user)
		doc.visits_per_week = value
		doc.save()
	else:
		doc = frappe.get_doc({"doctype": DOCTYPE, "user": user, "visits_per_week": value}).insert()
	return {"user": user, "visits_per_week": doc.visits_per_week}
