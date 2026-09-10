# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


def get_permission_query_conditions(user=None):
	"""A rep sees their own suggestions; a manager sees their subtree's.

	The API endpoints scope by ``user`` too, but they are not the only door: the
	generic document API reaches this doctype directly, so the rule has to live
	on the doctype or it is not a rule.

	An unowned suggestion -- a signal on a record with no owner -- belongs to
	nobody's queue and is listed only for a viewer whose ``visible_users`` is
	unrestricted. That is the same set of people who can read an unowned deal:
	``crm.permissions.org_hierarchy`` shows an in-tree manager the records their
	subtree owns or is assigned, and an ownerless one is neither. Listing the
	suggestion to them anyway gave every team lead rows they could neither open
	nor act on -- accept and dismiss check the record and threw "not permitted".
	"""
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users

	user = user or frappe.session.user
	users = visible_users(user)
	if users is None:
		return ""
	escaped = ", ".join(frappe.db.escape(name) for name in users)
	return f"`tabCRM Suggestion`.`user` in ({escaped})"


def has_permission(doc, ptype="read", user=None):
	"""The record door, answering exactly as the list door does."""
	from crm.fcrm.doctype.crm_rep_plan.crm_rep_plan import visible_users

	user = user or frappe.session.user
	users = visible_users(user)
	if users is None:
		return True
	if not doc.user:
		# unowned suggestions are listed only to an unrestricted viewer, so they
		# are actionable only by one
		return False
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
