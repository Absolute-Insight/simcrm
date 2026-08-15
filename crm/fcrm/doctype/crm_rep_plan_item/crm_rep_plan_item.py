# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
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

		activity_type: DF.Literal["Call", "Meeting", "Task", "Email"]
		fulfilled_by: DF.DynamicLink | None
		fulfilled_by_doctype: DF.Link | None
		manual_override: DF.Check
		note: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		planned_date: DF.Date
		reference_docname: DF.DynamicLink | None
		reference_doctype: DF.Link | None
		status: DF.Literal["Planned", "Done", "Missed"]
		suggestion: DF.Link | None
	# end: auto-generated types
