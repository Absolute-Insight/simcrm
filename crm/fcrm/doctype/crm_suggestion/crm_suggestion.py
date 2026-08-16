# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


def get_permission_query_conditions(user=None):
	"""A rep sees their own suggestions; managers see the whole queue.

	The API endpoints scope by ``user`` too, but they are not the only door: the
	generic document API reaches this doctype directly, so the rule has to live
	on the doctype or it is not a rule.
	"""
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users

	user = user or frappe.session.user
	users = visible_users(user)
	if users is None:
		return ""
	# an unowned suggestion is a team-wide signal with no rep attached; it stays
	# visible to anyone who manages a team rather than belonging to one of them
	escaped = ", ".join(frappe.db.escape(name) for name in users)
	own = f"`tabCRM Suggestion`.`user` in ({escaped})"
	if "Sales Manager" in frappe.get_roles(user):
		return f"({own} or ifnull(`tabCRM Suggestion`.`user`, '') = '')"
	return own


def has_permission(doc, ptype="read", user=None):
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users

	user = user or frappe.session.user
	users = visible_users(user)
	if users is None:
		return True
	if not doc.user:
		# unowned suggestions are team-wide signals and stay in manager views only
		return "Sales Manager" in frappe.get_roles(user)
	return doc.user in users


class CRMSuggestion(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action_payload: DF.JSON | None
		dismiss_reason: DF.SmallText | None
		expires_on: DF.Datetime | None
		factors: DF.JSON | None
		name: DF.Int | None
		rationale: DF.SmallText | None
		reference_docname: DF.DynamicLink | None
		reference_doctype: DF.Link
		score: DF.Float
		signal: DF.Data
		status: DF.Literal["Open", "Accepted", "Dismissed", "Expired"]
		suggested_action: DF.Literal["create_task", "schedule_call", "send_reply", "update_field"]
		title: DF.Data
		user: DF.Link | None
	# end: auto-generated types

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Title", "type": "Data", "key": "title", "width": "20rem"},
			{"label": "Signal", "type": "Data", "key": "signal", "width": "10rem"},
			{"label": "Status", "type": "Select", "key": "status", "width": "8rem"},
			{"label": "For User", "type": "Link", "key": "user", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = [
			"name",
			"title",
			"signal",
			"status",
			"user",
			"reference_doctype",
			"reference_docname",
			"suggested_action",
			"rationale",
			"score",
			"modified",
		]
		return {"columns": columns, "rows": rows}
