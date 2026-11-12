# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Visit targets: the rep list behind Settings -> Visit Targets, and the pro-ration.

A target is a number of customer visits per working week, or per calendar
month (``CRM Visit Target``; the monthly number wins when both are set). Every
period is pro-rated by its working days, Monday to Friday -- the same idea as
quota's pro-ration by covered days. A weekly target is spread evenly over every
working day; a monthly one over the working days of each month, so a whole
month reads exactly the monthly number however many working days it has.

Writing a target is a manager act, guarded exactly like quota: only managers,
only for their own subtree, and never their own row unless they administer the
site. The guards are quota's own (``crm.api.quota``), not a copy of them.
"""

from __future__ import annotations

import math
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_months, cstr, get_first_day, get_last_day, getdate

from crm.api.quota import _is_manager, _not_the_caller, _only_own_team
from crm.utils import sales_user_only

DOCTYPE = "CRM Visit Target"

# far above any real week (MBP's managers talk about 15) and well inside the
# Int column, so a stray keystroke is refused rather than stored
MAX_VISITS_PER_WEEK = 200
# the same ceiling over a month's ~22 working days
MAX_VISITS_PER_MONTH = 900


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


def monthly_share(per_month, from_date, to_date) -> float:
	"""``per_month`` spread over each calendar month's working days, summed over
	the part of every month that [from_date, to_date] covers."""
	start, end = getdate(from_date), getdate(to_date)
	total = 0.0
	month = get_first_day(start)
	while month <= end:
		last = getdate(get_last_day(month))
		covered = working_days(max(start, month), min(end, last))
		if covered:
			total += per_month * covered / working_days(month, last)
		month = getdate(add_months(month, 1))
	return total


def target_for(users, from_date, to_date) -> dict[str, float]:
	"""``{user: visits due in [from_date, to_date]}`` for each rep that has a target.

	A monthly target is pro-rated by :func:`monthly_share`; a weekly one is
	visits_per_week x working days / 5. One query. A rep with no row, or a row
	of 0 (the form's default), is left out: no target is not a target of
	nothing, and the callers report it as "No target" rather than as on track.
	"""
	users = sorted({u for u in users or [] if u})
	if not users:
		return {}
	days = working_days(from_date, to_date)
	rows = frappe.get_all(
		DOCTYPE,
		filters={"user": ("in", users)},
		or_filters={"visits_per_week": (">", 0), "visits_per_month": (">", 0)},
		fields=["user", "visits_per_week", "visits_per_month"],
	)
	return {
		row.user: monthly_share(row.visits_per_month, from_date, to_date)
		if row.visits_per_month
		else row.visits_per_week * days / 5
		for row in rows
	}


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
	targets = {
		row.user: row
		for row in frappe.get_all(
			DOCTYPE, filters={"user": ("in", users)}, fields=["user", "visits_per_week", "visits_per_month"]
		)
	}
	rows = [
		{
			"user": user,
			"full_name": names.get(user) or user,
			"visits_per_week": (targets.get(user) or {}).get("visits_per_week") or None,
			"visits_per_month": (targets.get(user) or {}).get("visits_per_month") or None,
			"editable": _can_write(user),
		}
		for user in users
	]
	rows.sort(key=lambda r: (r["full_name"] or r["user"]).lower())
	return rows


@frappe.whitelist()
@sales_user_only
def set_visit_target(
	user: str,
	visits_per_week: int | str | None = None,
	visits_per_month: int | str | None = None,
):
	"""Set one rep's weekly or monthly visit target, whichever is passed; 0 or
	blank clears that one. The row goes when neither is left."""
	_only_managers()
	_only_own_team(user)
	_not_the_caller(user)
	from crm.api.rep_plan import planning_reps

	# the people the grid lists, so a rep locked out before go-live still gets one
	if user not in planning_reps():
		frappe.throw(_("{0} is not a sales user.").format(user))

	changes = {}
	if visits_per_week is not None:
		changes["visits_per_week"] = _whole_visits(visits_per_week, MAX_VISITS_PER_WEEK, _("a week"))
	if visits_per_month is not None:
		changes["visits_per_month"] = _whole_visits(visits_per_month, MAX_VISITS_PER_MONTH, _("a month"))
	if not changes:
		frappe.throw(_("Give a weekly or a monthly visit target."))

	exists = frappe.db.exists(DOCTYPE, user)
	stored = (
		frappe.db.get_value(DOCTYPE, user, ["visits_per_week", "visits_per_month"], as_dict=True)
		if exists
		else frappe._dict()
	)
	merged = {
		"visits_per_week": int(stored.get("visits_per_week") or 0),
		"visits_per_month": int(stored.get("visits_per_month") or 0),
		**changes,
	}
	if not any(merged.values()):
		if exists:
			# through the document, so has_permission is asked as well as the role
			frappe.delete_doc(DOCTYPE, user)
		return {"user": user, "visits_per_week": None, "visits_per_month": None}

	if exists:
		doc = frappe.get_doc(DOCTYPE, user)
		doc.update(changes)
		doc.save()
	else:
		doc = frappe.get_doc({"doctype": DOCTYPE, "user": user, **merged}).insert()
	return {
		"user": user,
		"visits_per_week": doc.visits_per_week or None,
		"visits_per_month": doc.visits_per_month or None,
	}


def _whole_visits(raw_value, ceiling: int, per: str) -> int:
	"""A target cell as a whole, non-negative number of visits, at most ``ceiling``."""
	raw = cstr(raw_value).strip()
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
	if value > ceiling:
		frappe.throw(_("A visit target is at most {0} {1}.").format(ceiling, per))
	return int(value)
