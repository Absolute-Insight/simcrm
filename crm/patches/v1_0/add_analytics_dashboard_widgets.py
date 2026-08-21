# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Bring forecast accuracy and deals-by-industry to layouts that already exist.

Both charts have been in the Add Chart picker for a while, but a picker is an
opt-in nobody exercises for a metric they do not know exists. They are now in
the default layout for fresh installs; this merges them into saved layouts the
same additive, idempotent way ``add_vectora_dashboard_widgets`` established --
a rearranged dashboard keeps its arrangement and only gains what is missing.

The x/w/h here are the placement used when the layout has no opinion; y is
recomputed to sit below the existing widgets by ``merge_widgets``.
"""

from crm.patches.v1_0.add_vectora_dashboard_widgets import merge_widgets

WIDGETS = [
	{
		"name": "forecast_accuracy",
		"type": "axis_chart",
		"layout": {"x": 0, "y": 0, "w": 10, "h": 9, "i": "forecast_accuracy"},
	},
	{
		"name": "deals_by_industry",
		"type": "axis_chart",
		"layout": {"x": 10, "y": 0, "w": 10, "h": 9, "i": "deals_by_industry"},
	},
]


def execute():
	merge_widgets(WIDGETS)
