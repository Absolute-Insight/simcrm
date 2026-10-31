# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

READABLE = ("read", "select", "report", "export", "print", "email")

# What the matcher, complete_item and cancel_item write on an item. crm.api.rep_plan
# never takes these from a client (its EDITABLE_ITEM_FIELDS); validate refuses them
# from the generic document API, the other door into this doctype.
SERVER_ITEM_FIELDS = ("status", "outcome", "fulfilled_by_doctype", "fulfilled_by", "manual_override")


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

	from crm.api.access import manager_outside_hierarchy_sees_all

	# A Sales Manager outside the tree sees everything -- unless an administrator
	# has said otherwise. The historical answer is the fallback (see
	# manager_outside_hierarchy_sees_all), so an existing site is unchanged; a
	# new install is set to "Own records only", without which defaulting the
	# hierarchy on does nothing on a site whose tree nobody has built yet.
	if "Sales Manager" in roles and manager_outside_hierarchy_sees_all():
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

	Ownership is read from the stored row, not the in-memory document: frappe
	checks write permission on the document *after* ``set_value``/``save`` have
	applied the caller's changes, so a rep who rewrote ``user`` to themselves
	looked like the owner. ``validate`` refuses that change as well.
	"""
	user = user or frappe.session.user
	owner = doc.user
	if doc.name and not doc.get("__islocal"):
		owner = frappe.db.get_value("CRM Rep Plan", doc.name, "user") or doc.user
	if owner == user:
		return True
	users = visible_users(user)
	return ptype in READABLE and (users is None or owner in users)


def on_doctype_update():
	"""One plan per rep-week, enforced where two concurrent saves cannot slip past it.

	``validate`` reads before it writes, so two requests that both find no plan
	both insert one and the adherence tile then counts the week twice.

	This runs on every migrate and so does exactly one thing: add the index. It
	deliberately does **not** clean up duplicates — deleting a rep's planned week
	is not something a schema sync should do quietly, and it once did. The
	merging cleanup is a one-time patch
	(``crm.patches.v1_0.merge_duplicate_rep_plan_weeks``) that runs earlier in the
	same migrate, keeps every item, and prints what it touched.
	"""
	try:
		frappe.db.add_unique("CRM Rep Plan", ["user", "week_start"], constraint_name="unique_user_week")
	except Exception:
		# A migrate must not abort here, and must not "fix" it by deleting data.
		# Without the index the read-then-throw in validate is still the guard, as
		# it was before; the operator gets told what to resolve.
		frappe.log_error(
			title="CRM Rep Plan: could not add the unique (user, week_start) index",
			message=(
				"Duplicate rep-weeks are present, so the index was not created and concurrent "
				"saves can still double a week.\n\nRun "
				"`bench --site <site> execute crm.patches.v1_0.merge_duplicate_rep_plan_weeks.execute` "
				"to merge them (it keeps every planned item), then migrate again.\n\n"
				+ frappe.get_traceback()
			),
		)


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
		# A plan is never handed to another user. Nothing legitimate moves a week
		# from one rep to another, and allowing it let a rep take over a colleague's
		# plan -- items, fulfilment state and all -- by rewriting `user` through
		# frappe.client.set_value: frappe checks write permission on the already
		# mutated document, so the thief looked like the owner.
		if not self.is_new() and self.has_value_changed("user"):
			frappe.throw(_("A plan cannot be moved to another user."), frappe.PermissionError)

		self._refuse_client_fulfilment()

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

	def _refuse_client_fulfilment(self):
		"""An item's status and what fulfilled it are the server's to write.

		``crm.api.rep_plan`` takes only the editable fields from a client. The
		generic document API is a second door: frappe.client.set_value on an item
		saves the rep's own plan, which she may write, and it let her name a
		colleague's Cancelled event as her item's fulfilment -- which
		clear_override then deleted -- or claim a colleague's meeting, so that
		colleague's own item could never be fulfilled by it.

		Server code saves with ignore_permissions and is trusted with these fields,
		the way frappe trusts it past a higher permlevel; so is Administrator.
		"""
		if self.flags.ignore_permissions or frappe.session.user == "Administrator":
			return
		for item in self.items:
			# frappe loads each stored row before validate; a new row has none
			stored = item.get_doc_before_save()
			if stored is None and not item.is_new():
				# a named row frappe found nowhere in this plan: saving it would
				# UPDATE that row by name, moving a colleague's item into this week
				frappe.throw(
					_("Plan item {0} is not part of this plan.").format(item.name), frappe.PermissionError
				)
			for field in SERVER_ITEM_FIELDS:
				if _server_value(field, item.get(field)) != _server_value(
					field, stored.get(field) if stored else None
				):
					frappe.throw(
						_("{0} of a planned activity is set by the planner, not edited directly.").format(
							_(item.meta.get_label(field))
						),
						frappe.PermissionError,
					)


def _server_value(field: str, value):
	"""A server-owned item field as compared by validate, with a new row's defaults."""
	if field == "manual_override":
		return frappe.utils.cint(value)
	if field == "status":
		return value or "Planned"
	return frappe.utils.cstr(value) or None
