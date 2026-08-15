# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMDashboard(Document):
	pass


# The curated tile row above the grid already answers "how many leads, open,
# won, adherence, attainment" (Dashboard.vue TILE_CATALOGUE), so the default
# grid must not answer it again: the same metric twice on one page is the
# two-answers-to-one-question failure, and once the two are computed by
# different code paths they will eventually disagree. The grid's number cards
# are only the metrics the tile row does NOT carry. Existing sites keep their
# saved layouts — this default applies to fresh installs and Reset to Default.
CURATED_TILE_METRICS = (
	"total_leads",
	"ongoing_deals",
	"won_deals",
	"plan_adherence",
	"quota_attainment",
)


def default_manager_dashboard_layout():
	"""
	Returns the default layout for the CRM Manager Dashboard.
	"""
	return '[{"name":"average_time_to_close_a_lead","type":"number_chart","tooltip":"Average time taken to close a lead","layout":{"x":0,"y":0,"w":4,"h":3,"i":"average_time_to_close_a_lead"}},{"name":"average_time_to_close_a_deal","type":"number_chart","layout":{"x":4,"y":0,"w":4,"h":3,"i":"average_time_to_close_a_deal"}},{"name":"average_deal_value","type":"number_chart","tooltip":"Average deal value of ongoing and won deals","layout":{"x":8,"y":0,"w":4,"h":3,"i":"average_deal_value"}},{"name":"average_won_deal_value","type":"number_chart","tooltip":"Average value of won deals","layout":{"x":12,"y":0,"w":4,"h":3,"i":"average_won_deal_value"}},{"name":"deals_at_risk","type":"number_chart","tooltip":"Open deals with a health score below 40","layout":{"x":16,"y":0,"w":4,"h":3,"i":"deals_at_risk"}},{"name":"sales_trend","type":"axis_chart","layout":{"x":0,"y":2,"w":10,"h":9,"i":"sales_trend"}},{"name":"forecasted_revenue","type":"axis_chart","layout":{"x":10,"y":2,"w":10,"h":9,"i":"forecasted_revenue"}},{"name":"funnel_conversion","type":"axis_chart","layout":{"x":0,"y":9,"w":10,"h":9,"i":"funnel_conversion"}},{"name":"deals_by_stage_donut","type":"donut_chart","layout":{"x":10,"y":9,"w":10,"h":9,"i":"deals_by_stage_donut"}},{"name":"leads_by_source","type":"donut_chart","layout":{"x":0,"y":16,"w":10,"h":9,"i":"leads_by_source"}},{"name":"deals_by_source","type":"donut_chart","layout":{"x":10,"y":16,"w":10,"h":9,"i":"deals_by_source"}},{"name":"deals_by_territory","type":"axis_chart","layout":{"x":0,"y":23,"w":10,"h":9,"i":"deals_by_territory"}},{"name":"deals_by_salesperson","type":"axis_chart","layout":{"x":10,"y":23,"w":10,"h":9,"i":"deals_by_salesperson"}},{"name":"lost_deal_reasons","type":"axis_chart","layout":{"x":0,"y":30,"w":20,"h":9,"i":"lost_deal_reasons"}}]'


def create_default_manager_dashboard(force=False):
	"""
	Creates the default CRM Manager Dashboard if it does not exist.
	"""
	if not frappe.db.exists("CRM Dashboard", "Manager Dashboard"):
		doc = frappe.new_doc("CRM Dashboard")
		doc.title = "Manager Dashboard"
		doc.layout = default_manager_dashboard_layout()
		doc.insert(ignore_permissions=True)
	else:
		doc = frappe.get_doc("CRM Dashboard", "Manager Dashboard")
		if force:
			doc.layout = default_manager_dashboard_layout()
			doc.save(ignore_permissions=True)
	return doc.layout
