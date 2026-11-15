# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A rep's revenue target for one month.

Monthly-per-rep is the whole model. Quarter, year and team quotas are sums over
these rows and are never stored, so a team number can never disagree with the
rep numbers underneath it — the same rule the metrics layer follows for every
other aggregate (PLAN.md: one source of numbers).

The amount is always in the CRM base currency. Deal values are normalised to
base via ``exchange_rate`` before they are compared with a quota, so attainment
never sums mixed currencies.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_first_day, getdate


class CRMQuota(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		currency: DF.Link | None
		period_start: DF.Date
		user: DF.Link
	# end: auto-generated types

	def before_naming(self):
		# autoname runs before validate, and the name is built from period_start —
		# so the snap has to happen here or "17 March" and "1 March" would become
		# two different names for the same rep-month and the primary key would
		# stop enforcing one target per month.
		self.snap_period_to_month_start()

	def validate(self):
		self.snap_period_to_month_start()
		self.stamp_base_currency()
		if self.amount < 0:
			frappe.throw(_("Quota cannot be negative."))

	def snap_period_to_month_start(self):
		"""A quota is a month, so the date that identifies it is that month's first day."""
		self.period_start = get_first_day(getdate(self.period_start))

	def stamp_base_currency(self):
		from crm.api.dashboard import get_base_currency

		self.currency = get_base_currency()


def get_permission_query_conditions(user=None):
	"""Reps see their own quota; managers see their subtree's.

	This used to return "" for anyone holding Sales Manager, which handed an
	in-tree manager every rep's target in the company — the exact thing
	SECURITY.md names as an invariant, and the thing the deal and plan queries
	beside it already honour. ``visible_users`` is the hierarchy the rest of the
	app scopes by, so Settings → Sales Targets now covers the same people a
	manager's deal tiles do.
	"""
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users

	user = user or frappe.session.user
	users = visible_users(user)
	if users is None:
		return ""
	escaped = ", ".join(frappe.db.escape(name) for name in users)
	return f"`tabCRM Quota`.`user` in ({escaped})"


def has_permission(doc, ptype="read", user=None):
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users

	user = user or frappe.session.user
	# both the rep the row is stored against and the one the caller has put on
	# it: the first decides whether they may touch the row at all, the second
	# whether they may give it to that person
	targets = {_stored_user(doc), _named_user(doc)}
	# Nobody writes their own target -- checked before the see-everyone shortcut,
	# because visible_users() is None for an out-of-tree Sales Manager on the
	# see-all setting too, not only for a System Manager, and that let such a
	# manager set their own target through the document API.
	if user in targets and ptype != "read" and not _sets_any_target(user):
		return False
	users = visible_users(user)
	if users is None:
		return True
	if not targets <= set(users):
		return False
	# Nobody writes their own target. A rep never could; a manager could, because
	# their own row is inside their own subtree — and attainment against a quota
	# is a compensation figure, so the person measured must not be the person who
	# typed the number. A System Manager is exempt (and is the one who sets a
	# manager's target); ``users is None`` above has already let them through.
	if user in targets:
		return ptype == "read"
	return True


def _stored_user(doc) -> str | None:
	"""Whose target this is as saved, not as the caller has rewritten it.

	frappe checks write on the document *after* ``set_value`` has applied the
	caller's values, so an in-tree manager who set ``user`` to one of their own
	reps on another team's quota passed the subtree check. ``user`` is
	set-only-once, so the save itself was refused further on -- but by a check
	that is not this one's to lean on, and only after write had been granted on a
	compensation figure outside the manager's team.
	"""
	if doc.name and not doc.get("__islocal"):
		stored = frappe.db.get_value("CRM Quota", doc.name, "user")
		if stored:
			return stored
	return doc.user


def _named_user(doc) -> str | None:
	"""The user on the document in hand, as the database spells them.

	Permission is checked before links are validated, and link validation then
	rewrites ``user`` to the stored spelling, which the database matches without
	regard to case. Compared as typed, a manager's own address in capitals was
	not "their own target" here and was saved as theirs a moment later.
	"""
	return (doc.user and frappe.db.get_value("User", doc.user, "name")) or doc.user


def _sets_any_target(user: str) -> bool:
	"""System Manager sets everyone's target, a manager's own included."""
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)
