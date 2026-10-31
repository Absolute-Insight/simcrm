# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Disable Status Changed automation rules that wait for a status their records cannot have.

The editor kept "Status becomes" when the author switched "Applies to", so a lead
rule could be saved waiting for a deal status; and ``to_status`` is Data, so a
status renamed or deleted after the rule was saved left it waiting for a name
that no longer exists. Either way the rule is listed as enabled and never fires.

Clearing the status is not the fix: an empty one widens the rule to fire on
every status change. Disabling it makes the list say what the rule does, and the
log names each one for an admin to pick a real status and turn it back on.
"""

import frappe

from crm.fcrm.doctype.crm_automation_rule.crm_automation_rule import STATUS_DOCTYPES


def execute():
	stale = []
	for document_type, status_doctype in STATUS_DOCTYPES.items():
		statuses = set(frappe.get_all(status_doctype, pluck="name"))
		rules = frappe.get_all(
			"CRM Automation Rule",
			filters={
				"enabled": 1,
				"trigger": "Status Changed",
				"document_type": document_type,
				"to_status": ("is", "set"),
			},
			fields=["name", "to_status"],
		)
		stale += [rule for rule in rules if rule.to_status not in statuses]
	if not stale:
		return

	for rule in stale:
		frappe.db.set_value("CRM Automation Rule", rule.name, "enabled", 0, update_modified=False)

	frappe.logger("crm.automation").info(
		f"CRM Automation Rule: disabled {len(stale)} rule(s) waiting for a status their"
		f" document type does not have: {', '.join(f'{r.name} ({r.to_status})' for r in stale)}"
	)
