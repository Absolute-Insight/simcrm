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

# Only metrics the curated tile row does NOT carry belong in the grid -- see
# CURATED_TILE_METRICS in crm_dashboard.py. This list once also merged
# plan_adherence and quota_attainment, which became curated tiles in a later
# commit; sites upgraded in between show both, and remove_duplicated_grid_tiles
# cleans that up. test_metrics guards the intersection so it cannot drift again.
#
# Now empty: its one remaining widget, deals_at_risk, became a curated tile too
# (and remove_duplicated_grid_tiles runs a second time to lift the grid copy).
# The module stays because the patch entry has run on real sites and because
# merge_widgets is the shared mechanism newer widget patches reuse.
WIDGETS = []


def merge_widgets(widgets: list[dict]) -> None:
	"""Add ``widgets`` to every saved layout that does not already carry them."""
	for name in frappe.get_all("CRM Dashboard", pluck="name"):
		layout = json.loads(frappe.db.get_value("CRM Dashboard", name, "layout") or "[]")
		present = {widget.get("name") for widget in layout}
		missing = [widget for widget in widgets if widget["name"] not in present]
		if not missing:
			continue

		# stack the new widgets below everything the layout already places, so a
		# rearranged dashboard never has one dropped on top of another. Rows are
		# filled by each widget's own width (the first version assumed 4-wide
		# tiles, which would overlap anything wider), wrapping at the grid's 20
		# columns.
		bottom = max(
			(w.get("layout", {}).get("y", 0) + w.get("layout", {}).get("h", 0) for w in layout), default=0
		)
		x = 0
		row_height = 0
		for widget in missing:
			widget = json.loads(json.dumps(widget))
			width = widget["layout"].get("w", 4)
			if x + width > 20:
				x = 0
				bottom += row_height
				row_height = 0
			widget["layout"]["x"] = x
			widget["layout"]["y"] = bottom
			x += width
			row_height = max(row_height, widget["layout"].get("h", 3))
			layout.append(widget)

		frappe.db.set_value("CRM Dashboard", name, "layout", json.dumps(layout))


def execute():
	merge_widgets(WIDGETS)
