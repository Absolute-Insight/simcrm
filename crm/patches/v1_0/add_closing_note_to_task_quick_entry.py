import json

import frappe

from crm.install import append_to_layout_column

LAYOUT = "CRM Task-Quick Entry"


def execute():
	"""Existing sites keep their stored quick-entry layout; put the new field where
	the status is. Fresh installs get it from add_default_fields_layout."""
	if not frappe.db.exists("CRM Fields Layout", LAYOUT):
		return
	layout = json.loads(frappe.db.get_value("CRM Fields Layout", LAYOUT, "layout") or "[]")
	if append_to_layout_column(layout, "status", "closing_note"):
		frappe.db.set_value("CRM Fields Layout", LAYOUT, "layout", json.dumps(layout))
