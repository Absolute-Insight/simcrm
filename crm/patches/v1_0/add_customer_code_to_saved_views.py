"""Put the Customer Code column on Organizations views already saved.

A user's standard view stores its columns the first time they filter or sort, and
from then on those are used instead of the defaults, so the new column would only
reach people who had never touched the list. A view someone built themselves is
theirs: it is left alone, and the code is in its column picker.
"""

import json

import frappe


def execute():
	if not frappe.get_meta("CRM Organization").has_field("acumatica_id"):
		return
	views = frappe.get_all(
		"CRM View Settings",
		filters={"dt": "CRM Organization", "type": "list", "is_standard": 1},
		fields=["name", "columns", "rows"],
		limit=0,
	)
	for view in views:
		add_customer_code(view)


def add_customer_code(view) -> None:
	try:
		columns = json.loads(view.columns or "[]")
		rows = json.loads(view.rows or "[]")
	except (TypeError, ValueError):
		return
	# saved views hold whatever the client sent, and a bad one must not stop a migrate
	if not isinstance(columns, list) or not isinstance(rows, list):
		return
	if not all(isinstance(column, dict) for column in columns):
		return
	if not columns or any(column.get("key") == "acumatica_id" for column in columns):
		return
	after = next((i for i, c in enumerate(columns) if c.get("key") == "organization_name"), -1)
	columns.insert(
		after + 1, {"label": "Customer Code", "type": "Data", "key": "acumatica_id", "width": "10rem"}
	)
	if "acumatica_id" not in rows:
		rows.append("acumatica_id")
	frappe.db.set_value(
		"CRM View Settings",
		view.name,
		{"columns": json.dumps(columns), "rows": json.dumps(rows)},
		update_modified=False,
	)
