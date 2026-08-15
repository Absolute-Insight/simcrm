# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Suggestion inbox endpoints.

Accept and dismiss only flip status on the suggestion — the actual record an
acceptance leads to (task, event, reply draft) is created client-side through
the normal create flow behind a formDialog() confirmation. That keeps this
API write-surface tiny and keeps the human confirmation as the write gate
(PLAN.md Phase 8, constraint 1).

Ownership is enforced here *and* on the doctype (see
``crm.fcrm.doctype.crm_suggestion.crm_suggestion``): these endpoints save with
``ignore_permissions`` because the state machine is theirs to enforce, so the
scoping they apply has to be their own, not the framework's.
"""

from __future__ import annotations

import frappe
from frappe import _

from crm.utils import sales_user_only

REFERENCE_DOCTYPES = ("CRM Deal", "CRM Lead")


def _is_manager() -> bool:
	roles = frappe.get_roles()
	return "Sales Manager" in roles or "System Manager" in roles


def _get_for_update(name: str):
	doc = frappe.get_doc("CRM Suggestion", name)
	# an unowned suggestion is a team-wide signal: manager-only, rather than
	# actionable by whichever rep names it first
	if not _is_manager() and doc.user != frappe.session.user:
		frappe.throw(
			_("This suggestion belongs to another user."),
			frappe.PermissionError,
		)
	# acting on a suggestion means acting on the record behind it; an orphan whose
	# record is already gone stays clearable, or it can never leave the inbox
	if doc.reference_doctype and frappe.db.exists(doc.reference_doctype, doc.reference_docname):
		frappe.has_permission(doc.reference_doctype, "read", doc=doc.reference_docname, throw=True)
	return doc


@frappe.whitelist()
@sales_user_only
def get_suggestions(reference_doctype: str | None = None, reference_docname: str | None = None):
	"""Open suggestions for the session user (all users for managers), newest first.

	Pass a reference to get the open suggestions for one record instead. The
	owner filter still applies: naming a record you can read is not a way to
	read another rep's queue for it.
	"""
	filters = {"status": "Open"}

	if reference_doctype and reference_docname:
		if reference_doctype not in REFERENCE_DOCTYPES:
			frappe.throw(_("Unsupported reference type."))
		frappe.has_permission(reference_doctype, "read", doc=reference_docname, throw=True)
		filters |= {
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
		}

	if not _is_manager():
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
@sales_user_only
def get_open_count():
	"""Open-suggestion count for the badge — same scoping as get_suggestions."""
	filters = {"status": "Open"}
	if not _is_manager():
		filters["user"] = frappe.session.user
	return frappe.db.count("CRM Suggestion", filters)


@frappe.whitelist()
@sales_user_only
def get_dismissal_stats(user: str | None = None):
	"""Dismissals per signal, with the reasons reps gave.

	The signal engine already reads these counts to stretch a repeat dismisser's
	cooldown (``crm.agent.signals.dedupe``); this is the same data made legible,
	so an administrator tuning ``CRM Agent Settings`` can see which threshold is
	being rejected rather than guessing at it.
	"""
	user = user or frappe.session.user
	if user != frappe.session.user and not _is_manager():
		frappe.throw(_("Only managers can read another user's dismissals."), frappe.PermissionError)

	rows = frappe.get_all(
		"CRM Suggestion",
		filters={"status": "Dismissed", "user": user},
		fields=["signal", "dismiss_reason", "modified"],
		order_by="modified desc",
		limit_page_length=500,
	)

	stats: dict[str, dict] = {}
	for row in rows:
		bucket = stats.setdefault(row.signal, {"signal": row.signal, "dismissals": 0, "reasons": []})
		bucket["dismissals"] += 1
		if row.dismiss_reason and len(bucket["reasons"]) < 5:
			bucket["reasons"].append(row.dismiss_reason)
	return sorted(stats.values(), key=lambda s: s["dismissals"], reverse=True)


@frappe.whitelist()
@sales_user_only
def accept(name: str):
	doc = _get_for_update(name)
	if doc.status != "Open":
		frappe.throw(_("Only open suggestions can be accepted."))
	doc.status = "Accepted"
	doc.save(ignore_permissions=True)
	return {"status": "Accepted"}


@frappe.whitelist()
@sales_user_only
def dismiss(name: str, reason: str | None = None):
	doc = _get_for_update(name)
	if doc.status != "Open":
		frappe.throw(_("Only open suggestions can be dismissed."))
	doc.status = "Dismissed"
	doc.dismiss_reason = reason
	doc.save(ignore_permissions=True)
	return {"status": "Dismissed"}
