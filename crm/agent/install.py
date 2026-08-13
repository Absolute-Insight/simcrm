# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Idempotent setup for the agent layer, run from ``after_install`` and ``after_migrate``.

The agent will authenticate as a real Frappe user holding this role, so its blast radius
is defined in a place reviewers already understand. Read-only by construction: write
permissions arrive in a later plan, with an approval gate shipped alongside them.

DocPerms for the role are deliberately deferred, and nothing here touches permissions.
``frappe.permissions.add_permission`` calls ``setup_custom_perms``, which copies a
doctype's standard ``DocPerm`` rows into ``Custom DocPerm`` the first time it runs for
that doctype; from then on ``get_valid_perms`` no longer extends it with standard perms,
so every later permission change shipped by frappe or by crm is silently discarded for
that doctype. Half the doctypes this role will eventually read (``Contact``,
``Communication``) are frappe core, shared with every app on the bench, and reverting
needs a manual ``reset_perms``. That is far too much collateral for a feature that is
off by default with a role assigned to nobody -- and nothing needs the perms yet: reads
run as the calling user, not as the agent. They land with the plan that introduces the
agent user, which is when they first do anything.
"""

from __future__ import annotations

import frappe

AGENT_ROLE = "CRM Agent"


def ensure_agent_role() -> None:
	"""Create the agent role if it is missing. Idempotent, and grants nothing on its own."""
	if not frappe.db.exists("Role", AGENT_ROLE):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": AGENT_ROLE,
				"desk_access": 0,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)
