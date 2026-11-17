# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Quota administration: the rep x month grid behind Settings -> Sales Targets.

Setting a target is a manager act, so every write here is guarded by role rather
than by ownership — a rep may read their own row (``CRM Quota``'s permission
query handles that) but may not author one.
"""

from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, getdate

from crm.api.dashboard import get_base_currency, visible_reps
from crm.fcrm.doctype.crm_quota.crm_quota import MAX_QUOTES_PER_MONTH


def _is_manager() -> bool:
	roles = frappe.get_roles()
	return "Sales Manager" in roles or "System Manager" in roles


def _only_managers():
	if not _is_manager():
		frappe.throw(_("Only a Sales Manager can set quota."), frappe.PermissionError)


def _only_own_team(user: str):
	"""A manager sets targets for their subtree, not for every rep on the site.

	``visible_reps`` is the same scope the dashboard and planner apply, so the
	people a manager can set a target for are exactly the people whose numbers
	they can read. ``None`` is unrestricted (Administrator, System Manager, a
	manager outside the hierarchy).
	"""
	reps = visible_reps()
	if reps is not None and user not in reps:
		frappe.throw(_("{0} is not on your team.").format(user), frappe.PermissionError)


def _not_the_caller(user: str):
	"""A manager does not set their own target.

	Attainment against a quota is a compensation figure, and ``visible_reps``
	always contains the caller, so the team check alone let a manager write the
	number they are then measured against. Only a System Manager -- who is
	administering the site rather than carrying a bag on it -- may set a target
	for themselves, and in practice sets everyone else's too.
	"""
	if user == frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("Your own target has to be set by an administrator."),
			frappe.PermissionError,
		)


def _months(year: int) -> list[str]:
	return [f"{year}-{month:02d}-01" for month in range(1, 13)]


@frappe.whitelist()
def get_quota_grid(year: int | str | None = None):
	"""Every rep's monthly target for ``year``, plus what they have actually closed.

	Managers get the whole team; a rep gets only their own row, so the same screen
	serves "set the team's targets" and "what is mine".
	"""
	from crm.api.dashboard import won_value_by_user

	year = cint(year) or getdate().year
	months = _months(year)

	if _is_manager():
		reps = visible_reps()
		# the subtree, kept to enabled sales users so a disabled rep does not get a row
		users = _sales_users() if reps is None else [u for u in _sales_users() if u in set(reps)]
	else:
		users = [frappe.session.user]
	if not users:
		return {"year": year, "months": months, "currency": get_base_currency(), "rows": []}

	rows = frappe.get_all(
		"CRM Quota",
		filters={
			"user": ("in", users),
			"period_start": ("between", [months[0], f"{year}-12-31"]),
		},
		fields=["user", "period_start", "amount", "quotes"],
	)
	by_user: dict[str, dict[str, float]] = {}
	quotes_by_user: dict[str, dict[str, int]] = {}
	for row in rows:
		# a row can hold either target without the other
		if flt(row.amount):
			by_user.setdefault(row.user, {})[str(row.period_start)] = flt(row.amount)
		if cint(row.quotes):
			quotes_by_user.setdefault(row.user, {})[str(row.period_start)] = cint(row.quotes)

	user_meta = {
		u.name: u.full_name
		for u in frappe.get_all("User", filters={"name": ("in", users)}, fields=["name", "full_name"])
	}

	# one grouped read for the whole grid rather than a closed-won query per rep
	actual = won_value_by_user(users, months[0], f"{year}-12-31")

	return {
		"year": year,
		"months": months,
		"currency": get_base_currency(),
		"rows": [
			{
				"user": user,
				"full_name": user_meta.get(user) or user,
				"quota": by_user.get(user, {}),
				"actual": actual.get(user, 0.0),
				"quotes": quotes_by_user.get(user, {}),
			}
			for user in sorted(users, key=lambda u: (user_meta.get(u) or u).lower())
		],
	}


def _sales_users() -> list[str]:
	"""Enabled users who can own a deal — the population a quota can apply to."""
	return frappe.get_all(
		"User",
		filters=[
			["User", "enabled", "=", 1],
			["Has Role", "role", "in", ("Sales User", "Sales Manager")],
		],
		pluck="name",
		distinct=True,
	)


KINDS = ("amount", "quotes")


def _kind(kind: str | None) -> str:
	kind = kind or "amount"
	if kind not in KINDS:
		frappe.throw(_("Unknown target."), frappe.ValidationError)
	return kind


def _write_target(user: str, period_start, kind: str, value):
	"""Set one target on a rep-month. The row goes when neither target is left."""
	name = frappe.db.exists("CRM Quota", {"user": user, "period_start": period_start})
	if not name:
		if not value:
			return 0
		doc = frappe.get_doc({"doctype": "CRM Quota", "user": user, "period_start": period_start})
		doc.set(kind, value)
		doc.insert(ignore_permissions=True)
		return doc.get(kind)
	doc = frappe.get_doc("CRM Quota", name)
	doc.set(kind, value)
	if not flt(doc.amount) and not cint(doc.quotes):
		frappe.delete_doc("CRM Quota", name, ignore_permissions=True)
		return 0
	doc.save(ignore_permissions=True)
	return doc.get(kind)


@frappe.whitelist()
def set_quota(
	user: str,
	period_start: str,
	amount: float | str | None = None,
	quotes: int | str | None = None,
):
	"""Upsert one cell of the grid: the revenue target (``amount``) or the number
	of quotes (``quotes``). Zero or blank clears that target for the month."""
	_only_managers()
	_only_own_team(user)
	_not_the_caller(user)
	if user not in _sales_users():
		frappe.throw(_("{0} is not a sales user.").format(user))

	period_start = get_first_day(getdate(period_start))
	if (quotes is None) == (amount is None):
		# one cell, one target: with both, guessing which was meant could clear
		# the other; with neither there is nothing to set
		frappe.throw(_("Set one target at a time."), frappe.ValidationError)
	if quotes is not None:
		try:
			count = float(quotes or 0)
		except (TypeError, ValueError):
			count = -1
		# nan and inf are floats too, and neither is a number of quotes
		if not math.isfinite(count) or count < 0 or count != int(count) or count > MAX_QUOTES_PER_MONTH:
			frappe.throw(
				_("Enter a whole number of quotes, 0 to {0}.").format(MAX_QUOTES_PER_MONTH),
				frappe.ValidationError,
			)
		return {"quotes": _write_target(user, period_start, "quotes", int(count))}

	amount = flt(amount)
	if amount < 0:
		frappe.throw(_("Quota cannot be negative."))
	return {"amount": _write_target(user, period_start, "amount", amount)}


@frappe.whitelist()
def copy_quota_forward(user: str, from_period: str, months: int | str = 11, kind: str = "amount"):
	"""Repeat one month's target across the following ``months`` — the common case
	when a target is flat for a year, and far less error-prone than typing twelve cells."""
	_only_managers()
	kind = _kind(kind)
	# scoped before the source is read, so the copy neither reveals nor
	# rewrites a target outside the caller's subtree
	_only_own_team(user)
	# ``set_quota`` refuses each write too, but only after the source row has been
	# read; refusing here stops the call before it reads anything
	_not_the_caller(user)
	source = get_first_day(getdate(from_period))
	value = frappe.db.get_value("CRM Quota", {"user": user, "period_start": source}, kind)
	if not value:
		frappe.throw(_("Set the first month's quota before copying it forward."))

	# at most the rest of a year: the grid is twelve cells wide, and an
	# unbounded count is a write loop the caller sizes
	months = max(0, min(cint(months), 11))
	for offset in range(1, months + 1):
		set_quota(user, frappe.utils.add_months(source, offset), **{kind: value})
	return {"copied": months}
