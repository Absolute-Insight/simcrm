# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Drop grid cards for metrics the curated tile row already carries.

``add_vectora_dashboard_widgets`` merged ``plan_adherence`` and
``quota_attainment`` into every saved layout as grid number cards. A later
commit made those two part of the curated tile row above the grid
(``CURATED_TILE_METRICS``), on the reasoning that one metric answered twice on
one page is two answers that will eventually disagree — but the patch that had
already run was never revisited. A site upgraded between those two commits
renders both; a fresh install never did, because ``install_app`` marks patches
complete without running them.

Only the grid copy goes. The tile row keeps rendering the metric, so nothing
disappears from the page — the duplicate does. Removing it is safe because
nothing else could have put it there: the Add Chart picker has never offered
either metric, so the widget patch is its only possible origin.

Run #2 (patches.txt suffix): ``deals_at_risk`` joined the curated tile row, and
the picker stopped offering the number cards the tile row carries. This time a
manager *could* have added the removed card through the picker — but the tile
row now shows the same number for every role, so lifting the grid copy still
removes only the duplicate, never the metric.
"""

import json

import frappe

from crm.fcrm.doctype.crm_dashboard.crm_dashboard import CURATED_TILE_METRICS


def execute():
	curated = set(CURATED_TILE_METRICS)

	for name in frappe.get_all("CRM Dashboard", pluck="name"):
		layout = json.loads(frappe.db.get_value("CRM Dashboard", name, "layout") or "[]")

		# a curated metric is only a duplicate as a grid *number card*; leaving any
		# other widget type alone keeps this narrow enough to be obviously correct
		kept = [
			widget
			for widget in layout
			if not (widget.get("name") in curated and widget.get("type") == "number_chart")
		]
		if len(kept) == len(layout):
			continue

		frappe.db.set_value("CRM Dashboard", name, "layout", json.dumps(kept))
