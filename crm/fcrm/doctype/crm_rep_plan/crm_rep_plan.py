# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

READABLE = ("read", "select", "report", "export", "print", "email")


def visible_users(user=None) -> list[str] | None:
	"""Whose plans ``user`` may read, or None for everyone.

	Plans follow the sales hierarchy that already scopes leads and deals, not the
	role on its own: an in-tree team lead is a Sales User who must see their own
	team, and an in-tree Sales Manager must not see outside theirs.
	"""
	from crm.permissions.org_hierarchy import _in_hierarchy, _team_mem_query, hierarchy_enabled

	user = user or frappe.session.user
	if user == "Administrator":
		return None

	roles = frappe.get_roles(user)
	if "System Manager" in roles:
		return None

	if hierarchy_enabled() and _in_hierarchy(user):
		return [user, *(_team_mem_query(user).run(pluck=True) or [])]

	if "Sales Manager" in roles:
		return None

	return [user]


def get_permission_query_conditions(user=None):
	"""Reps list their own plans; managers list their subtree's."""
	user = user or frappe.session.user
	users = visible_users(user)
	if users is None:
		return ""
	escaped = ", ".join(frappe.db.escape(name) for name in users)
	return f"`tabCRM Rep Plan`.`user` in ({escaped})"


def has_permission(doc, ptype="read", user=None):
	"""Managers read their subtree's plans; a plan is only ever *written* by its rep.

	``crm.api.rep_plan`` enforces the same rule, but the generic document API is a
	second door into this doctype and a rep editing a colleague's week through it
	would be indistinguishable from the colleague doing it.
	"""
	user = user or frappe.session.user
	if doc.user == user:
		return True
	users = visible_users(user)
	return ptype in READABLE and (users is None or doc.user in users)


def on_doctype_update():
	"""One plan per rep-week, enforced where two concurrent saves cannot slip past it.

	``validate`` reads before it writes, so two requests that both find no plan
	both insert one and the adherence tile then counts the week twice.
	"""
	_collapse_duplicate_weeks()
	frappe.db.add_unique("CRM Rep Plan", ["user", "week_start"], constraint_name="unique_user_week")


def _collapse_duplicate_weeks() -> None:
	"""Drop the emptier half of any duplicate rep-week left behind by the old race."""
	duplicates = frappe.db.sql(
		"""select `user`, week_start from `tabCRM Rep Plan`
		group by `user`, week_start having count(*) > 1""",
		as_dict=True,
	)
	for row in duplicates:
		plans = frappe.get_all(
			"CRM Rep Plan",
			filters={"user": row.user, "week_start": row.week_start},
			pluck="name",
		)
		counts = {
			name: frappe.db.count("CRM Rep Plan Item", {"parent": name, "parenttype": "CRM Rep Plan"})
			for name in plans
		}
		keep = max(plans, key=lambda name: (counts[name], name))
		for name in plans:
			if name != keep:
				frappe.delete_doc("CRM Rep Plan", name, force=True, ignore_permissions=True)


class CRMRepPlan(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from crm.fcrm.doctype.crm_rep_plan_item.crm_rep_plan_item import CRMRepPlanItem

		items: DF.Table[CRMRepPlanItem]
		name: DF.Int | None
		user: DF.Link
		week_start: DF.Date
	# end: auto-generated types

	def validate(self):
		week_start = getdate(self.week_start)
		if week_start.weekday() != 0:
			frappe.throw(_("Week start must be a Monday."))

		exists = frappe.db.exists(
			"CRM Rep Plan",
			{"user": self.user, "week_start": self.week_start, "name": ("!=", self.name)},
		)
		if exists:
			frappe.throw(_("A plan for {0} starting {1} already exists.").format(self.user, self.week_start))

		week_end = frappe.utils.add_days(week_start, 6)
		for item in self.items:
			planned = getdate(item.planned_date)
			if planned < week_start or planned > week_end:
				frappe.throw(
					_("Item '{0}' is planned outside the week of {1}.").format(
						item.note or item.activity_type, self.week_start
					)
				)
