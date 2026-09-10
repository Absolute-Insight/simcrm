# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Row scoping for the records that hang off a lead or a deal.

FCRM Note, CRM Task and CRM Call Log grant Sales User full CRUD and carried no
scoping of their own, so the Notes, Tasks and Call Logs pages -- and
``frappe.client.get_list`` straight from the browser -- read every note, task
description, phone number and recording URL on the site, whatever the hierarchy
hid on the deal itself. A rep could also delete a manager's task.

A row is visible when the lead or deal it hangs off is visible to the user
under :mod:`crm.permissions.org_hierarchy`, or when the row is the user's own:
its author, the task's assignee, the call's caller or receiver. That second
clause is not merely a fallback for unlinked rows -- a task is assigned to a rep
on a deal only their manager owns, and a call is logged against the agent who
took it -- so it has to hold even when the referenced record does not.

Two link shapes count, because both are in use: ``reference_doctype`` /
``reference_docname``, which the CRM writes when a note or task is created on a
record, and the ``links`` child table, which the Twilio and Exotel handlers
write when they match an incoming number to a lead or deal.

The document check reads the *stored* row, not the in-memory document: frappe
checks write on the mutated document, so a check against ``doc.reference_docname``
would let a rep re-point a hidden note at their own deal and read it.
"""

from __future__ import annotations

import frappe
from pypika import Criterion

from crm.permissions.org_hierarchy import _permission_query_conditions, sees_everything

#: Per doctype, the fields that name a user as the row's own.
OWN_FIELDS = {
	"FCRM Note": ("owner",),
	"CRM Task": ("owner", "assigned_to"),
	"CRM Call Log": ("owner", "caller", "receiver"),
}

#: The referenced doctypes that carry row scoping of their own.
SCOPED_REFERENCES = ("CRM Lead", "CRM Deal")


def _visible(user: str, reference: str):
	"""Sub-select of the ``reference`` rows this user may read."""
	Ref = frappe.qb.DocType(reference)
	query = frappe.qb.from_(Ref).select(Ref.name)
	conditions = _permission_query_conditions(user, reference)
	return query.where(conditions) if conditions else query


def _conditions(user: str, doctype: str):
	DT = frappe.qb.DocType(doctype)
	clauses = [DT[field] == user for field in OWN_FIELDS[doctype]]

	for reference in SCOPED_REFERENCES:
		visible = _visible(user, reference)
		clauses.append((DT.reference_doctype == reference) & DT.reference_docname.isin(visible))

		if doctype == "CRM Call Log":
			Link = frappe.qb.DocType("Dynamic Link").as_("_call_link")
			clauses.append(
				DT.name.isin(
					frappe.qb.from_(Link)
					.select(Link.parent)
					.where(
						(Link.parenttype == doctype)
						& (Link.link_doctype == reference)
						& Link.link_name.isin(_visible(user, reference))
					)
				)
			)

	return Criterion.any(clauses)


def get_permission_query_conditions(doctype: str, user: str | None = None) -> str:
	user = user or frappe.session.user
	if sees_everything(user):
		return ""
	return _conditions(user, doctype).get_sql(with_namespace=True, quote_char="`", secondary_quote_char="'")


def has_permission(doc, ptype: str, user: str | None, doctype: str) -> bool:
	user = user or frappe.session.user
	if sees_everything(user):
		return True
	if ptype == "create" or not doc.name:
		return True

	DT = frappe.qb.DocType(doctype)
	return bool(
		frappe.qb.from_(DT)
		.select(DT.name)
		.where(DT.name == doc.name)
		.where(_conditions(user, doctype))
		.limit(1)
		.run()
	)


def get_note_permission_query_conditions(user=None):
	return get_permission_query_conditions("FCRM Note", user)


def get_task_permission_query_conditions(user=None):
	return get_permission_query_conditions("CRM Task", user)


def get_call_log_permission_query_conditions(user=None):
	return get_permission_query_conditions("CRM Call Log", user)


def has_note_permission(doc, ptype, user):
	return has_permission(doc, ptype, user, "FCRM Note")


def has_task_permission(doc, ptype, user):
	return has_permission(doc, ptype, user, "CRM Task")


def has_call_log_permission(doc, ptype, user):
	return has_permission(doc, ptype, user, "CRM Call Log")
