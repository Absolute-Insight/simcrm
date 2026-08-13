# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The capability layer: everything the agent may read, and nothing else.

Deliberately narrow and deliberately boring. An MCP server is a thin adapter over
these functions, which is why they take primitives and return plain dicts.

Reads use ``frappe.get_list`` (permission-checked), never ``ignore_permissions``. The
agent sees exactly what its user sees. The one exception is the child read in
``read_thread``, which is gated on its parent instead -- see the comment there, and the
allowlist in ``tests/test_tools.py`` that pins the exception to that one call.
"""

from __future__ import annotations

import frappe
from frappe import _

SUPPORTED_DOCTYPES = ("CRM Deal", "CRM Lead")

# Always present as standard fields.
BASE_RECORD_FIELDS = ("name", "modified")
# Requested only when the doctype actually declares them -- Lead and Deal differ.
OPTIONAL_RECORD_FIELDS = ("organization", "status")
THREAD_FIELDS = ("name", "creation", "sender", "content")
DEFAULT_THREAD_LIMIT = 50
MAX_THREAD_LIMIT = 200


def read_record(doctype: str, name: str) -> dict:
	"""Fetch one record, honouring the current user's permissions."""
	_assert_supported(doctype)
	meta = frappe.get_meta(doctype)
	fields = [*BASE_RECORD_FIELDS, *(f for f in OPTIONAL_RECORD_FIELDS if meta.has_field(f))]
	rows = frappe.get_list(
		doctype,
		filters={"name": name},
		fields=fields,
		limit=1,
	)
	if not rows:
		raise frappe.DoesNotExistError(f"{doctype} {name} not found or not permitted")
	return dict(rows[0])


def read_thread(doctype: str, name: str, limit: int = DEFAULT_THREAD_LIMIT) -> list[dict]:
	"""Fetch the Communications linked to a record, newest first.

	Authority derives from the parent: ``read_record`` runs first, so a missing or
	unreadable record raises before a single child row is touched.
	"""
	_assert_supported(doctype)
	# The parent gate. Raises DoesNotExistError unless this user may read the record.
	read_record(doctype, name)

	# Deliberate, bounded exception to this module's get_list-only rule. frappe
	# registers a permission_query_condition for Communication
	# (get_permission_query_conditions_for_communication) that keeps only rows whose
	# email_account is one of the *reading user's own* User Email rows, and for a user
	# with none returns `communication_medium != 'Email'` -- excluding the entire email
	# thread. CRM ships Sales User and Sales Manager, neither of which is System
	# Manager or Super Email User, so get_list here handed every ordinary CRM user an
	# empty thread while the endpoint still reported success: a confident summary of a
	# conversation nobody read. That filter answers "which mailboxes are yours", which
	# is not the question being asked -- a record's timeline is a property of the
	# record. So authority comes from the read_record call above, the same parent-gated
	# shape frappe's own get_docinfo timeline uses, and the rows below are hard-scoped
	# to that one parent by filters that are not caller-controlled beyond it.
	rows = frappe.get_all(
		"Communication",
		filters={"reference_doctype": doctype, "reference_name": name},
		fields=list(THREAD_FIELDS),
		order_by="creation desc",
		limit=_clamp_limit(limit),
	)
	return [dict(row) for row in rows]


def _clamp_limit(limit) -> int:
	"""Force ``limit`` into ``1..MAX_THREAD_LIMIT``.

	An MCP client passes arbitrary arguments here. ``limit=0`` is falsy in frappe's
	query builder and therefore silently means *unbounded*, and a negative value is a
	SQL error rather than a validation error; anything unparseable falls back to the
	default rather than raising.
	"""
	try:
		value = int(limit)
	except (TypeError, ValueError):
		return DEFAULT_THREAD_LIMIT
	return max(1, min(value, MAX_THREAD_LIMIT))


def _assert_supported(doctype: str) -> None:
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("The agent cannot read {0}.").format(doctype), frappe.ValidationError)
