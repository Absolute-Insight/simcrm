# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Metrics-layer tests: plan adherence, at-risk deals, forecast and snapshots.

These run against the shared dev site, so every assertion is scoped to a
dedicated test user or measures deltas — never absolute site-wide counts
(see test_dashboard for how absolute counts rot on a dirty site). For the same
reason nothing here truncates a table: deletes name the suite's own fixtures.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.tests import IntegrationTestCase

from crm.api.dashboard import (
	get_chart,
	get_deals_at_risk,
	get_forecast_accuracy,
	get_forecasted_revenue,
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
		self.clear_fixtures()
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Metrics Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)

	def tearDown(self):
		self.clear_fixtures()
		super().tearDown()

	def clear_fixtures(self):
		for name in frappe.get_all("CRM Rep Plan", filters={"user": USER}, pluck="name"):
			frappe.delete_doc("CRM Rep Plan", name, force=True, ignore_permissions=True)
		frappe.db.delete("CRM Forecast Snapshot", {"user": ("in", [USER, ""])})

	def make_deal(self, **values):
		deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.org, "deal_owner": USER, **values}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True)
		return deal

	def status_of_type(self, type_: str) -> str:
		names = frappe.get_all("CRM Deal Status", filters={"type": type_}, pluck="name")
		if not names:
			self.skipTest(f"site has no {type_} deal status")
		return names[0]

	# --- plan adherence -------------------------------------------------

	def test_plan_adherence_counts_only_settled_items(self):
		today = frappe.utils.getdate()
		monday = frappe.utils.add_days(today, -today.weekday())
		yesterday = frappe.utils.add_days(today, -1)
		if yesterday < monday:
			self.skipTest("no settled day inside this week yet")
		items = [
			{"activity_type": "Task", "planned_date": yesterday, "status": "Done"},
			{"activity_type": "Call", "planned_date": yesterday, "status": "Missed"},
			# today's items are not matched until tonight's job runs, so counting
			# them would dock the rep for work they may already have done
			{"activity_type": "Email", "planned_date": today, "status": "Planned"},
		]
		frappe.get_doc(
			{"doctype": "CRM Rep Plan", "user": USER, "week_start": monday, "items": items}
		).insert(ignore_permissions=True)

		out = get_plan_adherence(str(monday), str(frappe.utils.add_days(monday, 6)), USER)
		self.assertEqual(out["value"], 50)
		self.assertEqual(out["suffix"], "%")

	def test_today_is_not_counted_because_it_has_not_settled(self):
		"""Fulfilment is written by the nightly match_actuals job, so today's items
		are neither credited nor held against anyone until tomorrow."""
		today = frappe.utils.getdate()
		monday = frappe.utils.add_days(today, -today.weekday())
		frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": USER,
				"week_start": monday,
				"items": [{"activity_type": "Task", "planned_date": today, "status": "Done"}],
			}
		).insert(ignore_permissions=True)

		out = get_plan_adherence(str(today), str(today), USER)
		self.assertEqual(out["value"], 0)

	def test_plan_adherence_reports_movement_against_the_previous_period(self):
		today = frappe.utils.getdate()
		monday = frappe.utils.add_days(today, -today.weekday())
		last_monday = frappe.utils.add_days(monday, -7)
		frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": USER,
				"week_start": last_monday,
				"items": [
					{"activity_type": "Task", "planned_date": last_monday, "status": "Done"},
					{"activity_type": "Call", "planned_date": last_monday, "status": "Missed"},
				],
			}
		).insert(ignore_permissions=True)

		# the week before last is empty, so last week's 50% is the whole movement
		out = get_plan_adherence(str(last_monday), str(frappe.utils.add_days(last_monday, 6)), USER)
		self.assertEqual(out["value"], 50)
		self.assertEqual(out["delta"], 50)

	def test_plan_adherence_with_no_plan_is_zero_not_an_error(self):
		today = str(frappe.utils.getdate())
		out = get_plan_adherence(today, today, USER)
		self.assertEqual(out["value"], 0)

	# --- deals at risk --------------------------------------------------

	def test_a_stale_deal_counts_as_at_risk_for_its_owner(self):
		deal = self.make_deal()
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

	def test_a_fresh_deal_with_an_open_task_is_not_at_risk(self):
		deal = self.make_deal()
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

	def test_an_overdue_expected_close_date_is_scored_as_overdue(self):
		"""closed_date is only ever set on a Won deal, and nothing scored here is
		won — reading it meant this factor could never fire."""
		from crm.api.dashboard import _at_risk_deals

		deal = self.make_deal(expected_closure_date=frappe.utils.add_days(frappe.utils.nowdate(), -10))
		verdict = next(d for d in _at_risk_deals(user=USER) if d["name"] == deal.name)
		overdue = next(f for f in verdict["factors"] if f["key"] == "close_overdue")
		self.assertEqual(overdue["weight"], 20)
		self.assertLess(verdict["score"], 100)

	# --- forecast -------------------------------------------------------

	def test_a_lost_deal_contributes_nothing_to_the_forecast(self):
		"""A Lost deal used to be forecast at 100% of its expected value, and its
		probability is not re-derived when the status changes outside the form."""
		month = frappe.utils.add_months(frappe.utils.get_first_day(frappe.utils.nowdate()), 1)
		self.make_deal(
			status=self.status_of_type("Open"),
			expected_deal_value=100_000,
			probability=50,
			exchange_rate=1,
			expected_closure_date=month,
		)
		lost = self.make_deal(
			expected_deal_value=100_000,
			probability=70,
			exchange_rate=1,
			expected_closure_date=month,
		)
		frappe.db.set_value("CRM Deal", lost.name, "status", self.status_of_type("Lost"))

		data = get_forecasted_revenue(str(month), str(frappe.utils.get_last_day(month)), USER)["data"]
		self.assertEqual([row["forecasted"] for row in data], [50_000])

	def test_revenue_lands_on_the_month_a_deal_closed_not_the_month_it_was_due(self):
		"""Actuals used to be grouped by expected_closure_date, so a deal that
		slipped two months was credited to the month it missed."""
		from crm.api.dashboard import won_value_in_period

		slipped = self.make_deal(
			expected_deal_value=80_000,
			probability=50,
			deal_value=60_000,
			exchange_rate=1,
			expected_closure_date="2026-01-15",
		)
		frappe.db.set_value(
			"CRM Deal",
			slipped.name,
			{"status": self.status_of_type("Won"), "closed_date": "2026-03-20"},
			update_modified=False,
		)
		self.make_deal(
			status=self.status_of_type("Open"),
			expected_deal_value=20_000,
			probability=50,
			exchange_rate=1,
			expected_closure_date="2026-01-20",
		)

		by_month = {
			row["month"]: row for row in get_forecasted_revenue("2026-01-01", "2026-03-31", USER)["data"]
		}
		# January keeps only the still-open pipeline; the won deal is no longer a forecast
		self.assertEqual(by_month["2026-01-01"]["forecasted"], 10_000)
		self.assertEqual(by_month["2026-01-01"]["actual"], 0)
		self.assertEqual(by_month["2026-03-01"]["actual"], 60_000)
		# and the forecast's actual is the same money the won-revenue metric reports
		self.assertEqual(
			by_month["2026-03-01"]["actual"], won_value_in_period("2026-03-01", "2026-03-31", USER)
		)

	def test_the_forecast_honours_the_range_it_is_given(self):
		self.make_deal(
			expected_deal_value=10_000,
			probability=50,
			exchange_rate=1,
			expected_closure_date="2032-06-15",
		)
		data = get_forecasted_revenue("2026-01-01", "2026-01-31", USER)["data"]
		self.assertTrue(all(row["month"].startswith("2026-01") for row in data), data)

	def test_a_settled_month_with_nothing_closed_reports_zero_not_a_gap(self):
		self.make_deal(
			expected_deal_value=10_000,
			probability=50,
			exchange_rate=1,
			expected_closure_date="2026-01-15",
		)
		row = get_forecasted_revenue("2026-01-01", "2026-01-31", USER)["data"][0]
		self.assertEqual(row["actual"], 0)

	# --- snapshots and accuracy -----------------------------------------

	def test_snapshot_job_is_idempotent_per_day(self):
		take_forecast_snapshot()
		first = frappe.db.count("CRM Forecast Snapshot")
		take_forecast_snapshot()
		self.assertEqual(frappe.db.count("CRM Forecast Snapshot"), first)

	def test_snapshots_are_taken_per_rep_as_well_as_site_wide(self):
		month = frappe.utils.add_months(frappe.utils.get_first_day(frappe.utils.nowdate()), 1)
		self.make_deal(
			expected_deal_value=40_000,
			probability=50,
			exchange_rate=1,
			expected_closure_date=month,
		)
		take_forecast_snapshot()

		mine = frappe.get_all(
			"CRM Forecast Snapshot",
			filters={"user": USER, "month": str(month)[:7]},
			fields=["forecasted"],
		)
		self.assertEqual([row.forecasted for row in mine], [20_000])

	def test_forecast_accuracy_uses_the_last_pre_month_snapshot(self):
		for snapshot_date, forecasted, actual in (
			("2026-06-20", 1000, 0),
			("2026-06-27", 1200, 100),
			("2026-07-15", 1300, 900),
		):
			snapshot = frappe.get_doc(
				{
					"doctype": "CRM Forecast Snapshot",
					"snapshot_date": snapshot_date,
					"month": "2026-07",
					"user": USER,
					"forecasted": forecasted,
					"actual_at_snapshot": actual,
				}
			).insert(ignore_permissions=True)
			self.addCleanup(frappe.delete_doc, "CRM Forecast Snapshot", snapshot.name, force=True)

		july = next(r for r in get_forecast_accuracy(user=USER)["data"] if r["month"] == "2026-07-01")
		self.assertEqual(july["forecasted"], 1200)  # the last forecast before July opened

	def test_forecast_accuracy_reads_the_actual_live_rather_than_from_the_snapshot(self):
		"""A month stops being snapshotted once it leaves the forecast window, so
		a frozen actual would understate attainment forever."""
		snapshot = frappe.get_doc(
			{
				"doctype": "CRM Forecast Snapshot",
				"snapshot_date": "2026-02-25",
				"month": "2026-03",
				"user": USER,
				"forecasted": 50_000,
				"actual_at_snapshot": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Forecast Snapshot", snapshot.name, force=True)

		deal = self.make_deal(deal_value=30_000, exchange_rate=1)
		frappe.db.set_value(
			"CRM Deal",
			deal.name,
			{"status": self.status_of_type("Won"), "closed_date": "2026-03-10"},
			update_modified=False,
		)

		march = next(r for r in get_forecast_accuracy(user=USER)["data"] if r["month"] == "2026-03-01")
		self.assertEqual(march["actual"], 30_000)

	# --- funnel ---------------------------------------------------------

	def test_the_funnel_counts_deals_that_were_later_lost(self):
		"""A funnel of survivors inflates every conversion rate below the leak, so
		a lost deal still counts for every stage it reached."""
		from crm.api.dashboard import get_funnel_conversion

		stages = frappe.get_all(
			"CRM Deal Status", filters={"type": ("in", ("Open", "Ongoing"))}, pluck="name", limit=1
		)
		if not stages:
			self.skipTest("site has no Open deal status")
		stage = stages[0]

		for type_ in ("Won", "Lost"):
			# both deals passed through the same stage on their way out
			deal = frappe.get_doc("CRM Deal", self.make_deal().name)
			deal.append("status_change_log", {"to": stage, "to_date": frappe.utils.now_datetime()})
			deal.save(ignore_permissions=True)
			frappe.db.set_value("CRM Deal", deal.name, "status", self.status_of_type(type_))

		today = str(frappe.utils.nowdate())
		data = get_funnel_conversion(today, today, USER)["data"]
		reached = next(row for row in data if row["stage"] == stage)
		self.assertEqual(reached["count"], 2)
		self.assertEqual(data[-1]["stage"], _("Lost"))
		self.assertEqual(data[-1]["count"], 1)

	def test_a_deal_that_re_enters_a_stage_is_still_one_deal(self):
		from crm.api.dashboard import get_deal_status_change_counts

		stages = frappe.get_all(
			"CRM Deal Status", filters={"type": ("in", ("Open", "Ongoing"))}, pluck="name", limit=1
		)
		if not stages:
			self.skipTest("site has no Open deal status")
		stage = stages[0]

		deal = frappe.get_doc("CRM Deal", self.make_deal().name)
		for _hop in range(2):
			deal.append("status_change_log", {"to": stage, "to_date": frappe.utils.now_datetime()})
		deal.save(ignore_permissions=True)

		today = str(frappe.utils.nowdate())
		rows = get_deal_status_change_counts(today, today, USER)
		self.assertEqual(next(r for r in rows if r["stage"] == stage)["count"], 1)

	# --- the chart registry ---------------------------------------------

	def test_only_registered_charts_are_reachable(self):
		"""The old getattr dispatch made every module function callable and passed
		the caller's user into whatever the third parameter happened to be."""
		out = get_chart("deal_status_change_counts", "axis", user=USER)
		self.assertIn("error", out)

	def test_every_default_dashboard_widget_has_a_chart(self):
		from crm.api.dashboard import CHARTS
		from crm.fcrm.doctype.crm_dashboard.crm_dashboard import default_manager_dashboard_layout

		names = {widget["name"] for widget in json.loads(default_manager_dashboard_layout())}
		self.assertEqual(names - set(CHARTS), set())


MANAGER = "metrics-manager@crmtest.test"
REP = "metrics-teamrep@crmtest.test"
OUTSIDER = "metrics-outsider@crmtest.test"


class ScopedMetricsTest(IntegrationTestCase):
	"""Aggregates answer the same question as the deal list beside them.

	Dashboard tiles are hand-built queries, so frappe never applies the CRM Deal
	permission query condition to them. These tests knock on that door: a number
	that includes a deal its reader cannot open is a hierarchy leak.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		for email, name, role in (
			(MANAGER, "Metrics Manager", "Sales Manager"),
			(REP, "Metrics Team Rep", "Sales User"),
			(OUTSIDER, "Metrics Outsider", "Sales User"),
		):
			if not frappe.db.exists("User", email):
				user = frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
				).insert(ignore_permissions=True)
				user.add_roles(role)

		self.was_enabled = frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)

		self.nodes = []
		manager_node = self.make_node(MANAGER, "Metrics Manager")
		self.make_node(REP, "Metrics Team Rep", reports_to=manager_node)

		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Scoped Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.status = frappe.get_all("CRM Deal Status", filters={"type": "Open"}, pluck="name")
		if not self.status:
			self.skipTest("site has no Open deal status")
		self.status = self.status[0]

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in reversed(self.nodes):
			frappe.delete_doc("CRM Sales Hierarchy", name, force=True, ignore_permissions=True)
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", self.was_enabled or 0)
		super().tearDown()

	def make_node(self, user: str, full_name: str, reports_to: str | None = None) -> str:
		node = frappe.get_doc(
			{
				"doctype": "CRM Sales Hierarchy",
				"user": user,
				"full_name": full_name,
				"reports_to": reports_to,
			}
		).insert(ignore_permissions=True)
		self.nodes.append(node.name)
		return node.name

	def make_deal(self, owner: str, value: float) -> str:
		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": self.org,
				"deal_owner": owner,
				"status": self.status,
				"expected_deal_value": value,
				"probability": 100,
				"exchange_rate": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True)
		return deal.name

	def pipeline_total(self) -> float:
		from crm.api.dashboard import pipeline_by_stage

		return sum(row["total_value"] for row in pipeline_by_stage())

	def test_an_in_tree_manager_does_not_see_an_out_of_subtree_deal(self):
		self.make_deal(REP, 10_000)
		self.make_deal(OUTSIDER, 90_000)

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(MANAGER)
		self.assertEqual(self.pipeline_total(), 10_000)

	def test_a_rep_sees_a_deal_assigned_to_them_by_todo(self):
		"""Ownership is not the only way a deal reaches a rep's list, so it cannot
		be the only way it reaches their pipeline number either."""
		name = self.make_deal(OUTSIDER, 25_000)
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "look at this deal",
				"reference_type": "CRM Deal",
				"reference_name": name,
				"allocated_to": REP,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "ToDo", todo.name, force=True)

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(REP)
		self.assertEqual(self.pipeline_total(), 25_000)

	def test_a_reps_own_tile_includes_a_deal_assigned_to_them(self):
		"""The same question through the real door.

		``get_chart`` pins ``user`` to the session user for a plain Sales User, and
		every aggregate then narrows on it — so a tile that reads only the owner
		field ANDs an assigned deal straight back out, and the rep's dashboard
		disagrees with the rep's deal list. This is that path, not the unscoped one.
		"""
		from crm.api.dashboard import pipeline_by_stage

		name = self.make_deal(OUTSIDER, 25_000)
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "look at this deal",
				"reference_type": "CRM Deal",
				"reference_name": name,
				"allocated_to": REP,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "ToDo", todo.name, force=True)

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(REP)
		scoped = sum(row["total_value"] for row in pipeline_by_stage(user=REP))
		self.assertEqual(scoped, 25_000)

	def test_the_tile_and_the_deal_page_score_a_deal_alike(self):
		"""One deal, two surfaces, one score.

		The at-risk tile extracts features in batch and the deal page extracts them
		one deal at a time. Whenever the batch path forgets a feature the factors
		that depend on it stop firing there, and the same deal quietly looks
		healthier on the dashboard than on its own page.
		"""
		from crm.agent.predict import get_deal_health
		from crm.api.dashboard import _at_risk_deals

		name = self.make_deal(REP, 10_000)
		old = frappe.utils.add_days(frappe.utils.now_datetime(), -30)
		frappe.db.set_value("CRM Deal", name, "creation", old, update_modified=False)

		tile = next(row for row in _at_risk_deals(user=REP) if row["name"] == name)
		page = get_deal_health(name)

		self.assertEqual(tile["score"], page["score"])
		self.assertEqual(
			[f["key"] for f in tile["factors"]],
			[f["key"] for f in page["factors"]],
		)

	def test_an_in_tree_manager_reads_plan_adherence_for_their_team_only(self):
		"""Plans are keyed on a user rather than a deal, so they get the subtree
		from the hierarchy instead of the deal permission condition."""
		from crm.api.dashboard import plan_adherence

		today = frappe.utils.getdate()
		monday = frappe.utils.add_days(today, -today.weekday())
		for owner in (REP, OUTSIDER):
			plan = frappe.get_doc(
				{
					"doctype": "CRM Rep Plan",
					"user": owner,
					"week_start": monday,
					"items": [{"activity_type": "Task", "planned_date": monday, "status": "Done"}],
				}
			).insert(ignore_permissions=True)
			self.addCleanup(frappe.delete_doc, "CRM Rep Plan", plan.name, force=True)

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(MANAGER)
		rows = plan_adherence(str(monday), str(frappe.utils.add_days(monday, 6)), group_by_user=True)
		self.assertEqual({row["user"] for row in rows}, {REP})
