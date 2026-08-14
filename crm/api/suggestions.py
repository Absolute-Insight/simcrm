# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Suggestion inbox endpoints.

Accept and dismiss only flip status on the suggestion — the actual record an
acceptance leads to (task, event, reply draft) is created client-side through
the normal create flow behind a formDialog() confirmation. That keeps this
API write-surface tiny and keeps the human confirmation as the write gate
(PLAN.md Phase 8, constraint 1).
"""

from __future__ import annotations

import frappe
from frappe import _


def _is_manager() -> bool:
	roles = frappe.get_roles()
	return "Sales Manager" in roles or "System Manager" in roles


def _get_for_update(name: str):
	doc = frappe.get_doc("CRM Suggestion", name)
	if doc.user and doc.user != frappe.session.user and not _is_manager():
		frappe.throw(
			_("This suggestion belongs to another user."),
			frappe.PermissionError,
		)
	return doc


@frappe.whitelist()
def get_suggestions(reference_doctype: str | None = None, reference_docname: str | None = None):
	"""Open suggestions for the session user (all users for managers), newest first.

	Pass a reference to get the open suggestions for one record instead.
	"""
	filters = {"status": "Open"}
	if reference_doctype and reference_docname:
		filters |= {
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
		}
	elif not _is_manager():
		# unowned suggestions surface only in manager views
		filters["user"] = frappe.session.user

	return frappe.get_list(
		"CRM Suggestion",
		filters=filters,
		fields=[
			"name",
			"signal",
			"title",
			"reference_doctype",
			"reference_docname",
			"user",
			"suggested_action",
			"action_payload",
			"rationale",
			"factors",
			"score",
			"creation",
		],
		order_by="score desc, creation desc",
		limit_page_length=50,
	)


@frappe.whitelist()
def accept(name: str):
	doc = _get_for_update(name)
	if doc.status != "Open":
		frappe.throw(_("Only open suggestions can be accepted."))
	doc.status = "Accepted"
	doc.save(ignore_permissions=True)
	return {"status": "Accepted"}


@frappe.whitelist()
def dismiss(name: str, reason: str | None = None):
	doc = _get_for_update(name)
	if doc.status != "Open":
		frappe.throw(_("Only open suggestions can be dismissed."))
	doc.status = "Dismissed"
	doc.dismiss_reason = reason
	doc.save(ignore_permissions=True)
	return {"status": "Dismissed"}
