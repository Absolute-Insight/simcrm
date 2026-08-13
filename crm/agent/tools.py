# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The capability layer: everything the agent may read, and nothing else.

Deliberately narrow and deliberately boring. An MCP server is a thin adapter over
these functions, which is why they take primitives and return plain dicts.

Reads use ``frappe.get_list`` (permission-checked), never ``frappe.get_all`` (which is
not), and never ``ignore_permissions``. The agent sees exactly what its user sees.
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
	"""Fetch the Communications linked to a record, newest first."""
	_assert_supported(doctype)
	rows = frappe.get_list(
		"Communication",
		filters={"reference_doctype": doctype, "reference_name": name},
		fields=list(THREAD_FIELDS),
		order_by="creation desc",
		limit=limit,
	)
	return [dict(row) for row in rows]


def _assert_supported(doctype: str) -> None:
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("The agent cannot read {0}.").format(doctype), frappe.ValidationError)
