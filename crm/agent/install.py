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

import os

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


# The three settings a container deployment cannot guess. `localhost` is the
# right shipped default for a bench on a laptop and the wrong one inside a
# compose network, where the inference server is a sibling service -- so a
# stack that ships its own model still had nothing pointing at it.
ENDPOINT_ENV = {
	"base_url": "VECTORA_AGENT_BASE_URL",
	"model": "VECTORA_AGENT_MODEL",
	"enabled": "VECTORA_AGENT_ENABLED",
}


def apply_endpoint_defaults() -> dict[str, str]:
	"""Seed the model endpoint from the environment at install time.

	Runs from ``after_install`` only, never from ``after_migrate``: this writes
	the admin's own settings, and a value re-applied on every upgrade would
	silently undo an endpoint or model an admin had changed in the UI, with
	nothing on screen to say why it moved back. Seeding once and then leaving it
	alone is the same contract the site's other install-time fixtures keep.

	``enabled`` is included because in a stack whose inference server is a
	sibling container the usual reason to ship the tier off -- don't send a
	customer's email to a third party unasked -- does not apply. Choosing to set
	the variable is the operator saying so. The doctype default stays 0 for a
	plain ``bench install-app crm``, where there is no endpoint to talk to.
	"""
	applied = {}
	for fieldname, var in ENDPOINT_ENV.items():
		value = (os.environ.get(var) or "").strip()
		if not value:
			continue
		if fieldname == "enabled":
			value = "1" if value.lower() in ("1", "true", "yes", "on") else "0"
		frappe.db.set_single_value("CRM Agent Settings", fieldname, value)
		applied[fieldname] = value

	if applied:
		frappe.clear_cache(doctype="CRM Agent Settings")
	return applied
