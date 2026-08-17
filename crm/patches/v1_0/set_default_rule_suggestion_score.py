# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Fill in ``suggestion_score`` on rules that predate the field.

Adding an Int column backfills existing rows with 0, not with the field's
default -- the default only applies to documents created afterwards. So without
this, every rule an admin had already written would keep working but file its
suggestions at urgency 0: bottom of every inbox, under every routine nudge,
with nothing on screen to say why. The rules would still be firing, which is the
worst version of the failure.

Only rows that are actually 0 are touched, and only ``Create Suggestion`` rules
-- the field is meaningless on a Create Task rule, and writing to those would
put a number in a box the admin never sees. A rule saved *after* the field
exists and deliberately set to 0 will not survive this patch if it is migrated
in the same run, which is the one case this gets wrong; a rule saved with the
default 60 is indistinguishable from one saved before the column existed, so
there is no fingerprint that separates them. Zero-as-a-choice is recoverable by
retyping it, whereas a silently-buried inbox is not, so the patch errs that way.
"""

import frappe

from crm.automation import DEFAULT_RULE_SUGGESTION_SCORE


def execute():
	if not frappe.db.has_column("CRM Automation Rule", "suggestion_score"):
		return

	stale = frappe.get_all(
		"CRM Automation Rule",
		filters={"action": "Create Suggestion", "suggestion_score": 0},
		pluck="name",
	)
	if not stale:
		return

	for name in stale:
		frappe.db.set_value(
			"CRM Automation Rule",
			name,
			"suggestion_score",
			DEFAULT_RULE_SUGGESTION_SCORE,
			update_modified=False,
		)

	frappe.logger("crm.automation").info(
		f"CRM Automation Rule: set suggestion_score to {DEFAULT_RULE_SUGGESTION_SCORE:g} on"
		f" {len(stale)} rule(s) that predated the field, so their suggestions keep the"
		" urgency they had before it existed."
	)
