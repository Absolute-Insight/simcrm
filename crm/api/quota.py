# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Quota administration: the rep x month grid behind Settings -> Sales Targets.

Setting a target is a manager act, so every write here is guarded by role rather
than by ownership — a rep may read their own row (``CRM Quota``'s permission
query handles that) but may not author one.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, getdate

from crm.api.dashboard import get_base_currency


def _is_manager() -> bool:
	roles = frappe.get_roles()
	return "Sales Manager" in roles or "System Manager" in roles


def _only_managers():
	if not _is_manager():
		frappe.throw(_("Only a Sales Manager can set quota."), frappe.PermissionError)


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

	users = _sales_users() if _is_manager() else [frappe.session.user]
	if not users:
		return {"year": year, "months": months, "currency": get_base_currency(), "rows": []}

	rows = frappe.get_all(
		"CRM Quota",
		filters={
			"user": ("in", users),
			"period_start": ("between", [months[0], f"{year}-12-31"]),
		},
		fields=["user", "period_start", "amount"],
	)
	by_user: dict[str, dict[str, float]] = {}
	for row in rows:
		by_user.setdefault(row.user, {})[str(row.period_start)] = flt(row.amount)

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


@frappe.whitelist()
def set_quota(user: str, period_start: str, amount: float | str):
	"""Upsert one cell of the grid. Zero or blank clears the target for that month."""
	_only_managers()
	if user not in _sales_users():
		frappe.throw(_("{0} is not a sales user.").format(user))

	period_start = get_first_day(getdate(period_start))
	amount = flt(amount)
	if amount < 0:
		frappe.throw(_("Quota cannot be negative."))

	name = frappe.db.exists("CRM Quota", {"user": user, "period_start": period_start})
	if not amount:
		if name:
			frappe.delete_doc("CRM Quota", name, ignore_permissions=True)
		return {"amount": 0}

	if name:
		doc = frappe.get_doc("CRM Quota", name)
		doc.amount = amount
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{"doctype": "CRM Quota", "user": user, "period_start": period_start, "amount": amount}
		).insert(ignore_permissions=True)
	return {"amount": doc.amount}


@frappe.whitelist()
def copy_quota_forward(user: str, from_period: str, months: int | str = 11):
	"""Repeat one month's target across the following ``months`` — the common case
	when a target is flat for a year, and far less error-prone than typing twelve cells."""
	_only_managers()
	source = get_first_day(getdate(from_period))
	amount = frappe.db.get_value("CRM Quota", {"user": user, "period_start": source}, "amount")
	if not amount:
		frappe.throw(_("Set the first month's quota before copying it forward."))

	# at most the rest of a year: the grid is twelve cells wide, and an
	# unbounded count is a write loop the caller sizes
	months = max(0, min(cint(months), 11))
	for offset in range(1, months + 1):
		set_quota(user, frappe.utils.add_months(source, offset), amount)
	return {"copied": months}
