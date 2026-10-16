# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""How many customer visits a rep should complete in a working week.

One row per rep, not per month like ``CRM Quota``: MBP's managers talk about
visits a week ("15 a week"), and a visit rate does not change month to month
the way a revenue target does. Any other period is pro-rated by its working
days (``crm.api.visit_targets.target_for``), so a month and a fortnight read
against the same weekly number.

Access follows the sales hierarchy exactly as quota does, including the rule
that nobody sets their own target.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class CRMVisitTarget(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		user: DF.Link
		visits_per_week: DF.Int
	# end: auto-generated types

	def validate(self):
		if (self.visits_per_week or 0) < 0:
			frappe.throw(_("A visit target cannot be negative."))


def get_permission_query_conditions(user=None):
	"""Reps see their own target; managers see their subtree's."""
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users

	user = user or frappe.session.user
	users = visible_users(user)
	if users is None:
		return ""
	escaped = ", ".join(frappe.db.escape(name) for name in users)
	return f"`tabCRM Visit Target`.`user` in ({escaped})"


def has_permission(doc, ptype="read", user=None):
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users

	user = user or frappe.session.user
	# Nobody writes their own target -- checked before the see-everyone shortcut,
	# because visible_users() is None for an out-of-tree Sales Manager on the
	# see-all setting too, not only for a System Manager, and that let such a
	# manager set their own target through the document API.
	if doc.user == user and ptype != "read" and not _sets_any_target(user):
		return False
	users = visible_users(user)
	if users is None:
		return True
	if doc.user not in users:
		return False
	# the person measured is not the person who types the number -- quota's rule
	if doc.user == user:
		return ptype == "read"
	return True


def _sets_any_target(user: str) -> bool:
	"""System Manager sets everyone's target, a manager's own included."""
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)
