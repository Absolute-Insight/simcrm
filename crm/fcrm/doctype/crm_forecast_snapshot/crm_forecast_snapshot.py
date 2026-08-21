# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMForecastSnapshot(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		actual_at_snapshot: DF.Float
		forecasted: DF.Float
		month: DF.Data
		name: DF.Int | None
		scope: DF.Literal["Rep", "Team", "Site"]
		snapshot_date: DF.Date
		user: DF.Link | None
	# end: auto-generated types


def on_doctype_update():
	"""One row per (day, month, scope, user), enforced by the table.

	``take_forecast_snapshot`` does an exists-then-insert, which two workers
	running the weekly job at once can both pass. ``user`` is written as ''
	rather than NULL for Site and Team rows because a unique index treats
	every NULL as distinct and would not catch the duplicate. Duplicates
	already present make the ALTER fail; that is logged, not "fixed" by
	deleting history.
	"""
	try:
		frappe.db.add_unique(
			"CRM Forecast Snapshot",
			["snapshot_date", "month", "scope", "user"],
			constraint_name="unique_snapshot_key",
		)
	except Exception:
		frappe.log_error(
			title="CRM Forecast Snapshot: could not add the unique snapshot key",
			message=(
				"Duplicate (snapshot_date, month, scope, user) rows are present, so the "
				"index was not created.\n\n" + frappe.get_traceback()
			),
		)
