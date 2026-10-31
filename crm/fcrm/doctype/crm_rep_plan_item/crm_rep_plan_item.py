# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


def on_doctype_update():
	"""The matcher walks a plan's rows by state on every daily run."""
	frappe.db.add_index("CRM Rep Plan Item", ["parent", "status"])


class CRMRepPlanItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		activity_type: DF.Literal[
			"Visit", "Unplanned Meeting", "Delivery", "Call", "Email", "Meeting", "Task", "Admin", "Reports"
		]
		fulfilled_by: DF.DynamicLink | None
		fulfilled_by_doctype: DF.Link | None
		manual_override: DF.Check
		note: DF.Data | None
		organization: DF.Link | None
		outcome: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		planned_date: DF.Date
		reference_docname: DF.DynamicLink | None
		reference_doctype: DF.Link | None
		status: DF.Literal["Planned", "Done", "Missed", "Cancelled"]
		suggestion: DF.Link | None
	# end: auto-generated types

	def validate(self):
		"""A planned activity is saved with its plan, never on its own.

		frappe runs this only when the row itself is saved or inserted -- a plan's
		save does not call its rows' controllers. That is a door past everything
		CRMRepPlan.validate checks: the REST resource API saves the row directly and
		then re-saves a plan that reads it back from the database unchanged, and
		frappe.client.save never re-saves the plan at all, so a rep could mark her
		own item Done with a colleague's meeting and the colleague's item could then
		never be fulfilled by it. The planner never writes a row this way.
		"""
		if self.flags.ignore_permissions or frappe.session.user == "Administrator":
			return
		frappe.throw(
			_("A planned activity is saved with its plan, not on its own."),
			frappe.PermissionError,
		)
