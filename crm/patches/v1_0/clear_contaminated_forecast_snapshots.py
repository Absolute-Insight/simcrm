# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Drop forecast snapshots taken while Lost deals counted at full value.

Every row written before that fix overstates the forecast by the whole value of
every deal lost that week, and there is no way to correct a stored total after
the fact. Forecast accuracy is measured against these rows, so a wrong history
is worse than no history — and nothing else reads them.
"""

import frappe


def execute():
	frappe.db.truncate("CRM Forecast Snapshot")
