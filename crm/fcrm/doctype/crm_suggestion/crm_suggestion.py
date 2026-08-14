# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMSuggestion(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action_payload: DF.JSON | None
		dismiss_reason: DF.SmallText | None
		expires_on: DF.Datetime | None
		factors: DF.JSON | None
		name: DF.Int | None
		rationale: DF.SmallText | None
		reference_docname: DF.DynamicLink
		reference_doctype: DF.Link
		score: DF.Float
		signal: DF.Data
		status: DF.Literal["Open", "Accepted", "Dismissed", "Expired"]
		suggested_action: DF.Literal["create_task", "schedule_call", "send_reply", "update_field"]
		title: DF.Data
		user: DF.Link | None
	# end: auto-generated types

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Title", "type": "Data", "key": "title", "width": "20rem"},
			{"label": "Signal", "type": "Data", "key": "signal", "width": "10rem"},
			{"label": "Status", "type": "Select", "key": "status", "width": "8rem"},
			{"label": "For User", "type": "Link", "key": "user", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = [
			"name",
			"title",
			"signal",
			"status",
			"user",
			"reference_doctype",
			"reference_docname",
			"suggested_action",
			"rationale",
			"score",
			"modified",
		]
		return {"columns": columns, "rows": rows}
