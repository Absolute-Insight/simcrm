# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""``analyst_data.run_plan``: CRM tables come from the metrics layer, ERP tables
from stubbed adapters, and an ERP failure marks its table rather than raising."""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent import analyst_data
from crm.integrations.acumatica.client import AcumaticaError


def make_won_deal(organization: str, value: float, closed_on: str) -> str:
	won = frappe.get_all("CRM Deal Status", filters={"type": "Won"}, pluck="name", limit=1)
	deal = frappe.get_doc(
		{
			"doctype": "CRM Deal",
			"organization": organization,
			"status": won[0],
			"deal_value": value,
			"exchange_rate": 1,
		}
	).insert()
	frappe.db.set_value("CRM Deal", deal.name, "closed_date", closed_on)
	return deal.name


class RunPlanTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("analyst_data")
		self.addCleanup(frappe.db.rollback, save_point="analyst_data")
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Analyst Data Org"})
			.insert()
			.name
		)

	def test_won_revenue_is_zero_filled_per_month_and_comes_from_the_metrics_layer(self):
		make_won_deal(self.org, 1500, "2026-05-15")
		tables = analyst_data.run_plan(
			{"metrics": ["won_revenue_by_month", "nope"], "from_date": "2026-04-01", "to_date": "2026-06-30"},
			None,
		)
		self.assertEqual([t["key"] for t in tables], ["won_revenue_by_month"])
		table = tables[0]
		self.assertEqual(table["source"], "CRM")
		self.assertEqual([row["month"] for row in table["rows"]], ["2026-04", "2026-05", "2026-06"])
		self.assertGreaterEqual(table["rows"][1]["value"], 1500)
		self.assertEqual(table["rows"][0]["value"], 0.0)
		self.assertIsNone(table["error"])

	def test_every_crm_metric_runs_without_error(self):
		"""The catalogue promises these; a runner that raises on an empty site is a bug."""
		keys = [key for key in analyst_data._CRM_RUNNERS]
		for start in range(0, len(keys), 4):
			plan = {"metrics": keys[start : start + 4], "from_date": "2026-01-01", "to_date": "2026-09-01"}
			tables = analyst_data.run_plan(plan, None)
			self.assertEqual([t["key"] for t in tables], plan["metrics"])
			for table in tables:
				self.assertIsInstance(table["rows"], list, table["key"])
				self.assertTrue(table["columns"], table["key"])

	def test_erp_metrics_are_skipped_without_an_erp(self):
		tables = analyst_data.run_plan(
			{"metrics": ["erp_cashflow_by_month"], "from_date": "2026-01-01", "to_date": "2026-03-31"}, None
		)
		self.assertEqual(tables, [])

	def test_erp_cashflow_sums_invoices_and_payments_per_month(self):
		invoices = [
			{"date": "2026-01-10", "amount": 100.0, "balance": 0.0, "due": "2026-02-09"},
			{"date": "2026-01-20", "amount": 50.0, "balance": 50.0, "due": "2026-02-19"},
			{"date": "2026-03-01", "amount": 70.0, "balance": 70.0, "due": "2026-03-31"},
		]
		payments = [{"date": "2026-01-15", "amount": 100.0}, {"date": "2026-02-02", "amount": 25.0}]
		with (
			mock.patch.object(analyst_data, "acumatica_invoices", return_value=invoices),
			mock.patch.object(analyst_data, "acumatica_payments", return_value=payments),
		):
			tables = analyst_data.run_plan(
				{
					"metrics": ["erp_cashflow_by_month", "erp_receivables"],
					"from_date": "2026-01-01",
					"to_date": "2026-03-31",
				},
				"acumatica",
			)
		cashflow, receivables = tables
		self.assertEqual(cashflow["source"], "Acumatica")
		self.assertEqual(
			cashflow["rows"],
			[
				{"month": "2026-01", "invoiced": 150.0, "received": 100.0, "net": -50.0},
				{"month": "2026-02", "invoiced": 0.0, "received": 25.0, "net": 25.0},
				{"month": "2026-03", "invoiced": 70.0, "received": 0.0, "net": -70.0},
			],
		)
		# as of 2026-03-31: the January balance is overdue (due 2026-02-19, > 30 days), March's is current
		self.assertEqual(
			receivables["rows"],
			[
				{"bucket": "Current", "amount": 70.0, "invoices": 1},
				{"bucket": "Overdue", "amount": 50.0, "invoices": 1},
			],
		)

	def test_an_unreachable_erp_marks_its_table_and_the_crm_table_still_runs(self):
		with mock.patch.object(analyst_data, "acumatica_invoices", side_effect=AcumaticaError("boom")):
			tables = analyst_data.run_plan(
				{
					"metrics": ["won_revenue_by_month", "erp_invoices_by_month"],
					"from_date": "2026-01-01",
					"to_date": "2026-02-28",
				},
				"acumatica",
			)
		self.assertEqual([t["key"] for t in tables], ["won_revenue_by_month", "erp_invoices_by_month"])
		self.assertIsNone(tables[0]["error"])
		self.assertEqual(tables[1]["error"], "unreachable")
		self.assertEqual(tables[1]["rows"], [])

	def test_enabled_erp_is_none_when_both_integrations_are_off(self):
		with mock.patch.object(frappe.db, "get_single_value", return_value=0):
			self.assertIsNone(analyst_data.enabled_erp())
