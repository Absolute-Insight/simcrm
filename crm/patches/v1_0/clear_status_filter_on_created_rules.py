# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Clear ``to_status`` on automation rules that do not fire on a status change.

The editor showed "Status becomes" only for a Status Changed rule, but kept the
value when the author switched the trigger to Created, and the engine applied
it whatever the trigger. Such a rule is listed as "When created" everywhere and
fires only for records created in that one status. ``validate`` now drops the
value on save; this clears the rules saved before it, so each one does what its
list row says.
"""

import frappe


def execute():
	stale = frappe.get_all(
		"CRM Automation Rule",
		filters={"trigger": ("!=", "Status Changed"), "to_status": ("is", "set")},
		pluck="name",
	)
	if not stale:
		return

	for name in stale:
		frappe.db.set_value("CRM Automation Rule", name, "to_status", None, update_modified=False)

	frappe.logger("crm.automation").info(
		f"CRM Automation Rule: cleared the hidden status filter on {len(stale)} rule(s)"
		f" that do not fire on a status change: {', '.join(stale)}"
	)
