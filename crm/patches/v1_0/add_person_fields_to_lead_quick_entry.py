import json

import frappe

from crm.install import append_to_layout_column

LAYOUT = "CRM Lead-Quick Entry"


def execute():
	if not frappe.db.exists("CRM Fields Layout", LAYOUT):
		return
	layout = json.loads(frappe.db.get_value("CRM Fields Layout", LAYOUT, "layout") or "[]")
	changed = append_to_layout_column(layout, "gender", "birthday")
	changed = append_to_layout_column(layout, "mobile_no", "contact_type") or changed
	if changed:
		frappe.db.set_value("CRM Fields Layout", LAYOUT, "layout", json.dumps(layout))
