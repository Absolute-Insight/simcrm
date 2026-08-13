# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Idempotent setup for the agent layer, run from ``after_migrate``.

The agent authenticates as a real Frappe user holding this role, so its blast radius
is defined in a place reviewers already understand. Read-only by construction: write
permissions arrive in a later plan, with an approval gate shipped alongside them.
"""

from __future__ import annotations

import frappe
from frappe.permissions import add_permission, update_permission_property

AGENT_ROLE = "CRM Agent"

READABLE_DOCTYPES = (
	"CRM Deal",
	"CRM Lead",
	"CRM Organization",
	"Contact",
	"Communication",
	"CRM Task",
)

# Permissions the role must never hold at this stage.
DENIED_PROPERTIES = ("write", "create", "delete", "submit", "cancel", "amend")


def ensure_agent_role() -> None:
	"""Create the agent role and its read-only permissions if they are missing."""
	if not frappe.db.exists("Role", AGENT_ROLE):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": AGENT_ROLE,
				"desk_access": 0,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)

	for doctype in READABLE_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": AGENT_ROLE}):
			add_permission(doctype, AGENT_ROLE, 0)
		update_permission_property(doctype, AGENT_ROLE, 0, "read", 1)
		for prop in DENIED_PROPERTIES:
			update_permission_property(doctype, AGENT_ROLE, 0, prop, 0)
