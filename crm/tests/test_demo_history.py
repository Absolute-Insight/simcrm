# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The two-year demo history: enough of it for every analytics window, and
gone without a trace when cleared."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.demo.history import MONTHS_BACK, create_demo_history, delete_demo_history
from crm.demo.users import DEMO_USER_EMAILS, create_demo_users, delete_demo_users


class DemoHistoryTest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_demo_users()
		cls.created = create_demo_history(DEMO_USER_EMAILS)

	@classmethod
	def tearDownClass(cls):
		delete_demo_history(cls.created)
		delete_demo_users(DEMO_USER_EMAILS)
		frappe.db.commit()
		super().tearDownClass()

	def test_every_month_of_the_window_has_leads_and_most_have_won_revenue(self):
		lead_dates = frappe.get_all(
			"CRM Lead", filters={"name": ["in", self.created["leads"]]}, pluck="creation"
		)
		months_with_leads = {str(d)[:7] for d in lead_dates}
		self.assertGreaterEqual(len(months_with_leads), MONTHS_BACK)

		closed = frappe.get_all(
			"CRM Deal", filters={"name": ["in", self.created["deals"]], "status": "Won"}, pluck="closed_date"
		)
		won_months = {str(d)[:7] for d in closed if d}
		self.assertGreaterEqual(len(won_months), MONTHS_BACK - 4)

	def test_the_dashboard_reads_the_history(self):
		from crm.api.dashboard import actual_by_month, forecast_accuracy_rows, plan_adherence, quota_in_period

		start = frappe.utils.add_months(frappe.utils.get_first_day(frappe.utils.today()), -12)
		end = frappe.utils.today()
		actual = actual_by_month(str(start), end)
		self.assertGreaterEqual(len([m for m, v in actual.items() if v > 0]), 8)
		self.assertGreater(quota_in_period(str(start), end), 0)
		adherence = plan_adherence(str(frappe.utils.add_days(end, -30)), end)[0]
		self.assertGreater(adherence["planned"], 0)
		self.assertTrue(any(row.get("forecasted") for row in forecast_accuracy_rows()))

	def test_open_deals_carry_a_stage_history_and_won_deals_a_closed_date(self):
		for name in self.created["deals"][:40]:
			deal = frappe.db.get_value("CRM Deal", name, ["status", "closed_date", "creation"], as_dict=True)
			logs = frappe.get_all(
				"CRM Status Change Log",
				filters={"parent": name},
				fields=["from_date", "to_date"],
				order_by="idx",
			)
			self.assertTrue(logs, name)
			self.assertEqual(str(logs[0]["from_date"])[:10], str(deal.creation)[:10], name)
			if deal.status == "Won":
				self.assertIsNotNone(deal.closed_date, name)
				self.assertLessEqual(str(deal.creation)[:10], str(deal.closed_date), name)

	def test_zz_delete_removes_everything_it_created(self):
		"""Runs last (unittest orders by name): tears the fixture down and checks nothing is left."""
		created = self.created
		delete_demo_history(created)
		for doctype, key in (
			("CRM Deal", "deals"),
			("CRM Lead", "leads"),
			("CRM Organization", "organizations"),
			("CRM Quota", "quotas"),
			("CRM Forecast Snapshot", "snapshots"),
			("CRM Rep Plan", "plans"),
			("Comment", "comments"),
		):
			names = created.get(key, [])
			if names:
				self.assertEqual(frappe.db.count(doctype, {"name": ["in", names]}), 0, doctype)
