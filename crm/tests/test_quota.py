# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Quota model and attainment tests.

Quota rows are monthly per rep; every other period is a sum over them. The
interesting behaviour is therefore at the edges — partial months, missing
quota, and the primary key that stops one rep-month having two targets.

Scoped to a dedicated test user throughout, because this suite runs against a
shared dev site (see test_metrics for the same convention).
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api import quota as quota_api
from crm.api.dashboard import (
	get_quota_attainment,
	quota_by_user,
	quota_in_period,
	won_value_by_user,
	won_value_in_period,
)
from crm.api.reports import get_report

USER = "quota-rep@crmtest.test"
OTHER = "quota-other@crmtest.test"


def ensure_user(email: str, name: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


class QuotaTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_user(USER, "Quota Rep")
		ensure_user(OTHER, "Quota Other")
		frappe.db.delete("CRM Quota", {"user": ("in", [USER, OTHER])})

	def tearDown(self):
		frappe.db.delete("CRM Quota", {"user": ("in", [USER, OTHER])})
		super().tearDown()

	def make_quota(self, period_start: str, amount: float, user: str = USER):
		return frappe.get_doc(
			{"doctype": "CRM Quota", "user": user, "period_start": period_start, "amount": amount}
		).insert(ignore_permissions=True)

	# --- the model -----------------------------------------------------

	def test_a_mid_month_date_snaps_to_the_month_it_names(self):
		quota = self.make_quota("2026-03-17", 50_000)
		self.assertEqual(str(quota.period_start), "2026-03-01")

	def test_one_rep_month_cannot_hold_two_targets(self):
		"""The name is built from (user, period_start), so the primary key enforces it —
		including when the second row names the month by a different day."""
		self.make_quota("2026-03-01", 50_000)
		with self.assertRaises(frappe.DuplicateEntryError):
			self.make_quota("2026-03-28", 90_000)

	def test_a_negative_target_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_quota("2026-03-01", -1)

	def test_the_row_records_the_base_currency_it_is_measured_in(self):
		quota = self.make_quota("2026-03-01", 50_000)
		self.assertEqual(quota.currency, frappe.db.get_single_value("FCRM Settings", "currency") or "USD")

	# --- summing over periods ------------------------------------------

	def test_a_full_month_range_is_exactly_that_months_quota(self):
		self.make_quota("2026-03-01", 50_000)
		self.assertEqual(quota_in_period("2026-03-01", "2026-03-31", USER), 50_000)

	def test_a_quarter_sums_its_months(self):
		self.make_quota("2026-01-01", 10_000)
		self.make_quota("2026-02-01", 20_000)
		self.make_quota("2026-03-01", 30_000)
		self.assertEqual(quota_in_period("2026-01-01", "2026-03-31", USER), 60_000)

	def test_a_partial_month_is_pro_rated_by_the_days_it_covers(self):
		"""31-day March, first 10 days covered -> 10/31 of the month's target."""
		self.make_quota("2026-03-01", 31_000)
		self.assertAlmostEqual(quota_in_period("2026-03-01", "2026-03-10", USER), 10_000, places=2)

	def test_a_range_spanning_two_months_pro_rates_both_ends(self):
		self.make_quota("2026-03-01", 31_000)  # 1000/day
		self.make_quota("2026-04-01", 30_000)  # 1000/day
		# 20-31 March (12 days) + 1-10 April (10 days)
		self.assertAlmostEqual(quota_in_period("2026-03-20", "2026-04-10", USER), 22_000, places=2)

	def test_another_reps_quota_is_never_counted(self):
		self.make_quota("2026-03-01", 50_000, user=OTHER)
		self.assertEqual(quota_in_period("2026-03-01", "2026-03-31", USER), 0)

	def test_a_period_with_no_quota_is_zero_not_an_error(self):
		self.assertEqual(quota_in_period("2026-03-01", "2026-03-31", USER), 0)

	def test_an_inverted_range_is_zero_rather_than_negative(self):
		self.make_quota("2026-03-01", 50_000)
		self.assertEqual(quota_in_period("2026-03-31", "2026-03-01", USER), 0)

	# --- attainment -----------------------------------------------------

	def test_attainment_without_a_quota_reports_zero_and_says_why(self):
		out = get_quota_attainment("2026-03-01", "2026-03-31", USER)
		self.assertEqual(out["value"], 0)
		self.assertIn("No quota", out["tooltip"])

	def test_attainment_is_won_revenue_over_quota(self):
		won_status = frappe.get_all("CRM Deal Status", filters={"type": "Won"}, pluck="name")
		if not won_status:
			self.skipTest("site has no Won deal status")
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Quota Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": org,
				"deal_owner": USER,
				"status": won_status[0],
				"deal_value": 25_000,
				"exchange_rate": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Deal", deal.name, "closed_date", "2026-03-15", update_modified=False)

		self.make_quota("2026-03-01", 50_000)
		self.assertEqual(won_value_in_period("2026-03-01", "2026-03-31", USER), 25_000)

		out = get_quota_attainment("2026-03-01", "2026-03-31", USER)
		self.assertEqual(out["value"], 50)
		self.assertEqual(out["suffix"], "%")

		frappe.delete_doc("CRM Deal", deal.name, force=True)

	def test_the_grouped_reads_agree_with_the_per_rep_ones(self):
		"""The report and the grid read every rep in one query; the tile reads
		one rep. Same rows, same pro-rating, same belonging -- including a deal
		assigned to a rep who does not own it, which counts for both of them."""
		won_status = frappe.get_all("CRM Deal Status", filters={"type": "Won"}, pluck="name")
		if not won_status:
			self.skipTest("site has no Won deal status")
		self.make_quota("2026-03-01", 30_000)
		self.make_quota("2026-04-01", 10_000, user=OTHER)
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Quota Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": org,
				"deal_owner": USER,
				"status": won_status[0],
				"deal_value": 8_000,
				"exchange_rate": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True)
		frappe.db.set_value("CRM Deal", deal.name, "closed_date", "2026-03-20", update_modified=False)
		from frappe.desk.form.assign_to import add as assign

		assign({"assign_to": [OTHER], "doctype": "CRM Deal", "name": deal.name})

		period = ("2026-03-10", "2026-04-15")
		self.assertEqual(
			won_value_by_user([USER, OTHER], *period),
			{USER: won_value_in_period(*period, USER), OTHER: won_value_in_period(*period, OTHER)},
		)
		self.assertEqual(won_value_by_user([USER, OTHER], *period)[OTHER], 8_000)
		self.assertEqual(
			quota_by_user([USER, OTHER], *period),
			{USER: quota_in_period(*period, USER), OTHER: quota_in_period(*period, OTHER)},
		)
		self.assertEqual(won_value_by_user([], *period), {})

	def test_the_report_and_the_tile_agree(self):
		"""One source of numbers: the report row must equal the dashboard tile."""
		self.make_quota("2026-03-01", 40_000)
		tile = get_quota_attainment("2026-03-01", "2026-03-31", USER)
		report = get_report("quota_attainment_by_rep", "2026-03-01", "2026-03-31", USER)
		row = next(r for r in report["rows"] if r["user"] == USER)
		self.assertEqual(row["quota"], 40_000)
		self.assertEqual(row["attainment"], tile["value"])


class QuotaGridApiTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_user(USER, "Quota Rep")
		ensure_user(OTHER, "Quota Other")
		frappe.db.delete("CRM Quota", {"user": ("in", [USER, OTHER])})

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Quota", {"user": ("in", [USER, OTHER])})
		super().tearDown()

	def test_setting_a_cell_creates_then_updates_one_row(self):
		quota_api.set_quota(USER, "2026-05-14", 12_000)
		quota_api.set_quota(USER, "2026-05-01", 15_000)
		rows = frappe.get_all("CRM Quota", filters={"user": USER}, fields=["period_start", "amount"])
		self.assertEqual(len(rows), 1)
		self.assertEqual(str(rows[0].period_start), "2026-05-01")
		self.assertEqual(rows[0].amount, 15_000)

	def test_clearing_a_cell_removes_the_row_rather_than_storing_a_zero(self):
		quota_api.set_quota(USER, "2026-05-01", 12_000)
		quota_api.set_quota(USER, "2026-05-01", 0)
		self.assertFalse(frappe.db.exists("CRM Quota", {"user": USER, "period_start": "2026-05-01"}))

	def test_copy_forward_repeats_the_month_across_the_year(self):
		quota_api.set_quota(USER, "2026-01-01", 10_000)
		quota_api.copy_quota_forward(USER, "2026-01-01", 11)
		rows = frappe.get_all("CRM Quota", filters={"user": USER}, pluck="amount")
		self.assertEqual(len(rows), 12)
		self.assertTrue(all(amount == 10_000 for amount in rows))

	def test_copy_forward_is_capped_at_the_rest_of_a_year(self):
		quota_api.set_quota(USER, "2026-01-01", 10_000)
		self.assertEqual(quota_api.copy_quota_forward(USER, "2026-01-01", 500), {"copied": 11})
		self.assertEqual(frappe.db.count("CRM Quota", {"user": USER}), 12)
		self.assertEqual(quota_api.copy_quota_forward(USER, "2026-01-01", -3), {"copied": 0})

	def test_a_disabled_user_is_not_a_sales_user(self):
		self.assertIn(OTHER, quota_api._sales_users())
		frappe.db.set_value("User", OTHER, "enabled", 0)
		self.addCleanup(frappe.db.set_value, "User", OTHER, "enabled", 1)
		self.assertNotIn(OTHER, quota_api._sales_users())

	def test_copy_forward_without_a_source_month_explains_itself(self):
		with self.assertRaises(frappe.ValidationError):
			quota_api.copy_quota_forward(USER, "2026-01-01", 3)

	def test_the_grid_returns_twelve_months_and_a_row_per_sales_user(self):
		quota_api.set_quota(USER, "2026-03-01", 20_000)
		grid = quota_api.get_quota_grid(2026)
		self.assertEqual(len(grid["months"]), 12)
		row = next(r for r in grid["rows"] if r["user"] == USER)
		self.assertEqual(row["quota"]["2026-03-01"], 20_000)

	def test_a_rep_sees_only_their_own_row_and_cannot_set_a_target(self):
		frappe.set_user(USER)
		grid = quota_api.get_quota_grid(2026)
		self.assertEqual([r["user"] for r in grid["rows"]], [USER])
		with self.assertRaises(frappe.PermissionError):
			quota_api.set_quota(OTHER, "2026-03-01", 99_000)


class QuotaPermissionTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		ensure_user(USER, "Quota Rep")
		ensure_user(OTHER, "Quota Other")
		frappe.db.delete("CRM Quota", {"user": ("in", [USER, OTHER])})
		frappe.get_doc(
			{"doctype": "CRM Quota", "user": OTHER, "period_start": "2026-03-01", "amount": 70_000}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Quota", {"user": ("in", [USER, OTHER])})
		super().tearDown()

	def test_a_rep_cannot_list_another_reps_target(self):
		frappe.set_user(USER)
		# get_list, not get_all: get_all deliberately bypasses permissions
		visible = frappe.get_list("CRM Quota", pluck="user")
		self.assertNotIn(OTHER, visible)

	def test_a_manager_sees_the_whole_team(self):
		frappe.set_user("Administrator")
		# get_list, not get_all: get_all deliberately bypasses permissions
		visible = frappe.get_list("CRM Quota", pluck="user")
		self.assertIn(OTHER, visible)
