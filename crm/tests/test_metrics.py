# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Metrics-layer tests: plan adherence, at-risk deals, forecast snapshots.

These run against the shared dev site, so every assertion is scoped to a
dedicated test user or measures deltas — never absolute site-wide counts
(see test_dashboard for how absolute counts rot on a dirty site).
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.dashboard import (
	get_deals_at_risk,
	get_forecast_accuracy,
	get_plan_adherence,
	take_forecast_snapshot,
)

USER = "metrics-rep@crmtest.test"


class MetricsTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": USER,
					"first_name": "Metrics Rep",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		frappe.db.delete("CRM Rep Plan")
		frappe.db.delete("CRM Forecast Snapshot")
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Metrics Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)

	def tearDown(self):
		frappe.db.delete("CRM Rep Plan")
		frappe.db.delete("CRM Forecast Snapshot")
		super().tearDown()

	def test_plan_adherence_counts_only_due_items(self):
		today = frappe.utils.getdate()
		monday = frappe.utils.add_days(today, -today.weekday())
		items = [
			{"activity_type": "Task", "planned_date": monday, "status": "Done"},
			{"activity_type": "Call", "planned_date": monday, "status": "Missed"},
		]
		# a future item inside the same week must not count against adherence
		if today.weekday() < 6:
			items.append(
				{
					"activity_type": "Email",
					"planned_date": frappe.utils.add_days(today, 1),
					"status": "Planned",
				}
			)
		frappe.get_doc(
			{"doctype": "CRM Rep Plan", "user": USER, "week_start": monday, "items": items}
		).insert(ignore_permissions=True)

		out = get_plan_adherence(str(monday), str(frappe.utils.add_days(monday, 6)), USER)
		self.assertEqual(out["value"], 50)
		self.assertEqual(out["suffix"], "%")

	def test_plan_adherence_with_no_plan_is_zero_not_an_error(self):
		today = str(frappe.utils.getdate())
		out = get_plan_adherence(today, today, USER)
		self.assertEqual(out["value"], 0)

	def test_a_stale_deal_counts_as_at_risk_for_its_owner(self):
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": self.org, "deal_owner": USER}).insert()
		old = frappe.utils.add_days(frappe.utils.now_datetime(), -40)
		frappe.db.set_value("CRM Deal", deal.name, "creation", old, update_modified=False)
		# rolled-back naming counters reuse deal names on this shared site, so
		# committed leftovers from earlier suites can reference this new name —
		# scrub them or the "stale" deal looks active
		for doctype, ref_field in (
			("CRM Task", "reference_docname"),
			("CRM Call Log", "reference_docname"),
			("Communication", "reference_name"),
			("Comment", "reference_name"),
		):
			frappe.db.delete(doctype, {"reference_doctype": "CRM Deal", ref_field: deal.name})

		out = get_deals_at_risk(user=USER)
		self.assertEqual(out["value"], 1)
		frappe.delete_doc("CRM Deal", deal.name, force=True)

	def test_a_fresh_deal_with_an_open_task_is_not_at_risk(self):
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": self.org, "deal_owner": USER}).insert()
		frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "next step",
				"status": "Todo",
				"reference_doctype": "CRM Deal",
				"reference_docname": deal.name,
			}
		).insert(ignore_permissions=True)

		out = get_deals_at_risk(user=USER)
		self.assertEqual(out["value"], 0)
		frappe.delete_doc("CRM Deal", deal.name, force=True)

	def test_snapshot_job_is_idempotent_per_day(self):
		take_forecast_snapshot()
		first = frappe.db.count("CRM Forecast Snapshot")
		take_forecast_snapshot()
		self.assertEqual(frappe.db.count("CRM Forecast Snapshot"), first)

	def test_forecast_accuracy_uses_the_earliest_pre_month_snapshot(self):
		for snapshot_date, forecasted, actual in (
			("2026-06-20", 1000, 0),
			("2026-06-27", 1200, 100),
			("2026-07-15", 1300, 900),
		):
			frappe.get_doc(
				{
					"doctype": "CRM Forecast Snapshot",
					"snapshot_date": snapshot_date,
					"month": "2026-07",
					"forecasted": forecasted,
					"actual_at_snapshot": actual,
				}
			).insert(ignore_permissions=True)

		rows = get_forecast_accuracy()
		july = next(r for r in rows if r["month"] == "2026-07")
		self.assertEqual(july["forecasted"], 1000)  # earliest pre-July snapshot
		self.assertEqual(july["actual"], 900)  # latest known actual
