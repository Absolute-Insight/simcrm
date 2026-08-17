"""Mixed into the Email Template controller by extend_doctype_class (see hooks.py).

A mixin rather than a subclass on purpose: it only adds the CRM list view's
column set, and mixins stack where a controller override does not.
"""


class EmailTemplateListView:
	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Name",
				"type": "Data",
				"key": "name",
				"width": "17rem",
			},
			{
				"label": "Subject",
				"type": "Data",
				"key": "subject",
				"width": "12rem",
			},
			{
				"label": "Enabled",
				"type": "Check",
				"key": "enabled",
				"width": "6rem",
			},
			{
				"label": "Doctype",
				"type": "Link",
				"key": "reference_doctype",
				"width": "12rem",
			},
			{
				"label": "Last Modified",
				"type": "Datetime",
				"key": "modified",
				"width": "8rem",
			},
		]
		rows = [
			"name",
			"enabled",
			"use_html",
			"reference_doctype",
			"subject",
			"response",
			"response_html",
			"modified",
		]
		return {"columns": columns, "rows": rows}
