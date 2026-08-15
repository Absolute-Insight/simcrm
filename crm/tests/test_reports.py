# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Report registry tests — shape, scoping, and agreement with the metrics layer.

The agreement tests are the point of the suite: a report and the dashboard tile
beside it answer the same question, so a report that grew its own aggregate
would be caught here rather than by a manager reading two different numbers.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.reports import REPORTS, get_report, list_reports

USER = "reports-rep@crmtest.test"


class ReportsTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": USER,
					"first_name": "Reports Rep",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		self.clear_fixtures()

	def tearDown(self):
		self.clear_fixtures()
		super().tearDown()

	def clear_fixtures(self):
		for name in frappe.get_all("CRM Rep Plan", filters={"user": USER}, pluck="name"):
			frappe.delete_doc("CRM Rep Plan", name, force=True, ignore_permissions=True)

	def test_every_registered_report_returns_its_declared_columns(self):
		today = str(frappe.utils.nowdate())
		for name in REPORTS:
			out = get_report(name, today, today)
			declared = {c["key"] for c in out["columns"]}
			for row in out["rows"]:
				self.assertEqual(
					set(row), declared, f"{name} row keys {set(row)} != declared columns {declared}"
				)

	def test_an_unknown_report_throws(self):
		with self.assertRaises(frappe.ValidationError):
			get_report("not_a_report")

	def test_list_reports_matches_the_registry(self):
		self.assertEqual({r["name"] for r in list_reports()}, set(REPORTS))

	def test_a_period_independent_report_says_so(self):
		"""The open pipeline is a snapshot of now — the UI needs to know not to
		offer a date range that would do nothing."""
		self.assertFalse(get_report("pipeline_by_stage")["period"])
		self.assertTrue(get_report("funnel_conversion")["period"])

	def test_plan_adherence_report_agrees_with_the_metric(self):
		from crm.api.dashboard import get_plan_adherence

		today = frappe.utils.getdate()
		monday = frappe.utils.add_days(today, -today.weekday())
		yesterday = frappe.utils.add_days(today, -1)
		if yesterday < monday:
			self.skipTest("no settled day inside this week yet")
		frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": USER,
				"week_start": monday,
				"items": [
					{"activity_type": "Task", "planned_date": yesterday, "status": "Done"},
					{"activity_type": "Call", "planned_date": yesterday, "status": "Missed"},
				],
			}
		).insert(ignore_permissions=True)

		start, end = str(monday), str(frappe.utils.add_days(monday, 6))
		report = get_report("plan_adherence_by_rep", start, end, USER)
		row = next(r for r in report["rows"] if r["user"] == USER)
		metric = get_plan_adherence(start, end, USER)
		self.assertEqual(row["adherence"], metric["value"])
		self.assertEqual(row["planned"], 2)

	def test_pipeline_report_agrees_with_the_stage_chart(self):
		"""One source of numbers: the report row and the dashboard chart count the
		same deals for the same stage."""
		from crm.api.dashboard import get_deals_by_stage_axis

		open_status = frappe.get_all("CRM Deal Status", filters={"type": "Open"}, pluck="name")
		if not open_status:
			self.skipTest("site has no Open deal status")
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Reports Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		for value in (10_000, 30_000):
			deal = frappe.get_doc(
				{
					"doctype": "CRM Deal",
					"organization": org,
					"deal_owner": USER,
					"status": open_status[0],
					"expected_deal_value": value,
					"probability": 50,
					"exchange_rate": 1,
				}
			).insert(ignore_permissions=True)
			self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True)

		today = str(frappe.utils.nowdate())
		report = get_report("pipeline_by_stage", today, today, USER)
		row = next(r for r in report["rows"] if r["stage"] == open_status[0])
		self.assertEqual(row["total_value"], 40_000)
		self.assertEqual(row["weighted_value"], 20_000)

		chart = get_deals_by_stage_axis(today, today, USER)
		tile = next(r for r in chart["data"] if r["stage"] == open_status[0])
		self.assertEqual(row["deals"], tile["count"])
		self.assertEqual(row["total_value"], tile["total_value"])

	def test_a_sales_user_is_scoped_to_themselves(self):
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user(USER)
		today = str(frappe.utils.nowdate())
		out = get_report("plan_adherence_by_rep", today, today, user=None)
		for row in out["rows"]:
			self.assertEqual(row["user"], USER)
