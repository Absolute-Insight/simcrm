# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Merge the Vectora tiles into a dashboard layout that already exists.

``create_default_manager_dashboard`` only writes the default layout when there
is no CRM Dashboard at all, so every tile this fork adds reaches new sites and
no upgraded one. Merging is additive and keyed on the widget name, so a layout
the customer has rearranged keeps its arrangement and only gains what is
missing; running the patch twice changes nothing the second time.
"""

import json

import frappe

WIDGETS = [
	{
		"name": "plan_adherence",
		"type": "number_chart",
		"tooltip": "Planned activities completed, out of those already due",
		"layout": {"x": 8, "y": 2, "w": 4, "h": 3, "i": "plan_adherence"},
	},
	{
		"name": "deals_at_risk",
		"type": "number_chart",
		"tooltip": "Open deals with a health score below 40",
		"layout": {"x": 12, "y": 2, "w": 4, "h": 3, "i": "deals_at_risk"},
	},
	{
		"name": "quota_attainment",
		"type": "number_chart",
		"tooltip": "Closed-won revenue against quota for the period",
		"layout": {"x": 16, "y": 2, "w": 4, "h": 3, "i": "quota_attainment"},
	},
]


def execute():
	for name in frappe.get_all("CRM Dashboard", pluck="name"):
		layout = json.loads(frappe.db.get_value("CRM Dashboard", name, "layout") or "[]")
		present = {widget.get("name") for widget in layout}
		missing = [widget for widget in WIDGETS if widget["name"] not in present]
		if not missing:
			continue

		# stack the new tiles below everything the layout already places, so a
		# rearranged dashboard never has a tile dropped on top of another
		bottom = max(
			(w.get("layout", {}).get("y", 0) + w.get("layout", {}).get("h", 0) for w in layout), default=0
		)
		for offset, widget in enumerate(missing):
			widget = json.loads(json.dumps(widget))
			widget["layout"]["y"] = bottom
			widget["layout"]["x"] = offset * 4 % 20
			layout.append(widget)

		frappe.db.set_value("CRM Dashboard", name, "layout", json.dumps(layout))
