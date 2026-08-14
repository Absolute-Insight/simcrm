# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMRepPlanItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		activity_type: DF.Literal["Call", "Meeting", "Task", "Email"]
		fulfilled_by: DF.DynamicLink | None
		fulfilled_by_doctype: DF.Link | None
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
