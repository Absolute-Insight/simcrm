# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


def get_permission_query_conditions(user=None):
	"""Reps list their own plans; managers list the team's."""
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	if "System Manager" in roles or "Sales Manager" in roles:
		return ""
	return f"`tabCRM Rep Plan`.`user` = {frappe.db.escape(user)}"


def has_permission(doc, ptype="read", user=None):
	"""Managers read any plan; a plan is only ever *written* by the rep who owns it.

	``crm.api.rep_plan`` enforces the same rule, but the generic document API is a
	second door into this doctype and a rep editing a colleague's week through it
	would be indistinguishable from the colleague doing it.
	"""
	user = user or frappe.session.user
	if doc.user == user:
		return True
	roles = frappe.get_roles(user)
	is_manager = "System Manager" in roles or "Sales Manager" in roles
	return is_manager and ptype in ("read", "select", "report", "export", "print", "email")


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
