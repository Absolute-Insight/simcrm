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

from crm.agent.predict import score_open_deals
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

		# the tile counts what the hourly scorer wrote, so score first — that is the
		# contract now, not an incidental ordering
		score_open_deals()
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

		score_open_deals()
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

	def test_a_failing_scope_costs_only_its_own_rows(self):
		"""One rep whose forecast raises must not abort the weekly run for the site."""
		from unittest.mock import patch

		from crm.api import dashboard

		# The deal needs a close date inside the snapshot window (today-1mo ..
		# today+6mo) or it buckets into no month, the site scope writes no rows,
		# and `written` is 0 whatever the failing rep does. Without it this
		# passed only on a site carrying deals left by an earlier run.
		self.make_deal(
			expected_deal_value=1_000,
			probability=50,
			exchange_rate=1,
			expected_closure_date=frappe.utils.add_months(
				frappe.utils.get_first_day(frappe.utils.nowdate()), 1
			),
		)
		real = dashboard.get_forecasted_revenue

		def explode(from_date, to_date, **kwargs):
			if kwargs.get("user") == USER:
				raise ValueError("bad rep")
			return real(from_date, to_date, **kwargs)

		with patch.object(dashboard, "get_forecasted_revenue", explode):
			written = take_forecast_snapshot()
		self.assertGreater(written, 0)
		self.assertTrue(frappe.get_all("CRM Forecast Snapshot", filters={"scope": "Site", "user": ""}))
		self.assertFalse(frappe.get_all("CRM Forecast Snapshot", filters={"scope": "Rep", "user": USER}))

	def test_a_duplicate_snapshot_row_is_refused_by_the_table(self):
		"""exists-then-insert can race; the unique key cannot."""
		if not frappe.db.sql(
			"select 1 from information_schema.TABLE_CONSTRAINTS where table_name=%s and CONSTRAINT_NAME=%s",
			("tabCRM Forecast Snapshot", "unique_snapshot_key"),
		):
			self.skipTest("unique_snapshot_key is not on this site yet (migrate adds it)")
		row = {
			"doctype": "CRM Forecast Snapshot",
			"snapshot_date": "2026-01-03",
			"month": "2026-02",
			"scope": "Rep",
			"user": USER,
			"forecasted": 1,
		}
		first = frappe.get_doc(row).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Forecast Snapshot", first.name, force=True)
		with self.assertRaises(frappe.UniqueValidationError):
			frappe.get_doc(row).insert(ignore_permissions=True)

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

	def test_default_grid_does_not_repeat_the_curated_tiles(self):
		"""The tile row above the grid already carries these metrics; the default
		grid showing them again is the same number answered twice on one page."""
		from crm.fcrm.doctype.crm_dashboard.crm_dashboard import (
			CURATED_TILE_METRICS,
			default_manager_dashboard_layout,
		)

		names = {widget["name"] for widget in json.loads(default_manager_dashboard_layout())}
		self.assertEqual(names & set(CURATED_TILE_METRICS), set())

	def test_the_widget_patch_does_not_repeat_the_curated_tiles(self):
		"""Same rule as the default layout, enforced where it actually broke.

		The patch predates CURATED_TILE_METRICS and merged two of them into every
		upgraded site's grid. The default-layout test above could not catch that,
		because the patch is a second, independent way for a widget to reach a
		layout."""
		from crm.fcrm.doctype.crm_dashboard.crm_dashboard import CURATED_TILE_METRICS
		from crm.patches.v1_0.add_vectora_dashboard_widgets import WIDGETS

		names = {widget["name"] for widget in WIDGETS}
		self.assertEqual(names & set(CURATED_TILE_METRICS), set())


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
		# plan_adherence only counts days that have settled (cutoff is yesterday),
		# so on a Monday this week has no countable day and every rep returns no
		# row -- the assertion below would read that emptiness as "the manager saw
		# nobody", which is a pass for the wrong reason on six days and a failure
		# on the seventh. test_reports guards its sibling case the same way.
		if frappe.utils.add_days(today, -1) < monday:
			self.skipTest("no settled day inside this week yet")
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

	def make_quota(self, user: str, amount: float) -> None:
		month = frappe.utils.get_first_day(frappe.utils.nowdate())
		quota = frappe.get_doc(
			{"doctype": "CRM Quota", "user": user, "period_start": month, "amount": amount}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Quota", quota.name, force=True)

	def test_quota_totals_cover_the_subtree_not_the_company(self):
		"""The numerator is permission-scoped, so the denominator must be too.

		quota_in_period reads through frappe.get_all, which does not check
		permissions, and quota is keyed on a user rather than a deal so nothing
		else narrows it. Unfiltered, a manager's subtree revenue was divided by
		every rep's target in the company and the tile under-reported badly."""
		from crm.api.dashboard import quota_in_period

		self.make_quota(REP, 1000)
		self.make_quota(OUTSIDER, 9000)

		month = str(frappe.utils.get_first_day(frappe.utils.nowdate()))
		month_end = str(frappe.utils.get_last_day(frappe.utils.nowdate()))

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(MANAGER)
		# the manager's own node carries no quota, so the subtree total is the
		# rep's 1000 -- the outsider's 9000 must not be in it
		self.assertEqual(quota_in_period(month, month_end), 1000)

	def test_the_quota_list_itself_is_scoped_to_the_subtree(self):
		"""SECURITY.md's rep-isolation invariant, asserted on the doctype.

		Scoping only the aggregate would leave Settings -> Sales Targets, which
		lists CRM Quota directly, showing every rep's number to any in-tree
		manager. The permission query returned "" for anyone holding Sales
		Manager, so it did."""
		self.make_quota(REP, 1000)
		self.make_quota(OUTSIDER, 9000)

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(MANAGER)
		owners = set(frappe.get_list("CRM Quota", pluck="user", limit_page_length=0))
		self.assertIn(REP, owners)
		self.assertNotIn(OUTSIDER, owners)

	def test_a_manager_cannot_name_a_rep_outside_their_subtree(self):
		"""The user parameter was trusted for anyone holding Sales Manager, so an
		in-tree one could read another team's figures by naming them."""
		from crm.api.dashboard import pin_user

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(MANAGER)

		self.assertEqual(pin_user(REP), REP)
		with self.assertRaises(frappe.PermissionError):
			pin_user(OUTSIDER)


class ForecastScopeTest(ScopedMetricsTest):
	"""Forecast accuracy reads a stored series, so scoping it is a separate
	question from scoping a live aggregate: the row has to have been *written*
	at the right scope weeks earlier, and picking the wrong stored row shows a
	manager a number that is not merely unscoped but about other people."""

	def make_deal(self, owner: str, value: float) -> str:
		"""The inherited helper leaves ``expected_closure_date`` unset, and every
		forecast query keys on it — so those deals are invisible to a forecast
		and a snapshot over them writes no rows at all."""
		name = super().make_deal(owner, value)
		frappe.db.set_value(
			"CRM Deal", name, "expected_closure_date", frappe.utils.get_last_day(frappe.utils.nowdate())
		)
		return name

	def snapshot_rows(self, **filters) -> list[dict]:
		return frappe.get_all(
			"CRM Forecast Snapshot",
			filters=filters,
			fields=["scope", "user", "month", "forecasted"],
		)

	def take_snapshot(self):
		from crm.api.dashboard import take_forecast_snapshot

		frappe.set_user("Administrator")
		take_forecast_snapshot()
		self.addCleanup(frappe.db.delete, "CRM Forecast Snapshot", {"snapshot_date": frappe.utils.nowdate()})

	def test_a_team_row_is_written_for_a_manager_with_reports(self):
		self.make_deal(REP, 10_000)
		self.take_snapshot()

		team = self.snapshot_rows(scope="Team", user=MANAGER)
		self.assertTrue(team, "no Team row was recorded for a manager with a subtree")
		self.assertTrue(any(row.forecasted for row in team))

	def test_no_team_row_is_written_for_a_leaf(self):
		"""A rep with no reports is not a team. Writing one would double every
		leaf's numbers into a scope that means something else."""
		self.make_deal(REP, 10_000)
		self.take_snapshot()

		self.assertEqual(self.snapshot_rows(scope="Team", user=REP), [])

	def test_a_team_row_covers_the_subtree_and_stops_there(self):
		self.make_deal(REP, 10_000)
		self.make_deal(OUTSIDER, 90_000)
		self.take_snapshot()

		month = frappe.utils.nowdate()[:7]
		team = self.snapshot_rows(scope="Team", user=MANAGER, month=month)
		site = self.snapshot_rows(scope="Site", user="", month=month)
		self.assertEqual(len(team), 1)
		# The manager's own subtree only -- the outsider's 90k is in Site.
		self.assertEqual(team[0].forecasted, 10_000)
		self.assertEqual(site[0].forecasted, 100_000)

	def test_a_manager_and_their_own_deals_get_separate_rows(self):
		"""A manager who sells is both a team and a rep, and the two numbers are
		different. The user field alone could not tell them apart, which is why
		scope exists."""
		self.make_deal(MANAGER, 5_000)
		self.make_deal(REP, 10_000)
		self.take_snapshot()

		month = frappe.utils.nowdate()[:7]
		team = self.snapshot_rows(scope="Team", user=MANAGER, month=month)
		own = self.snapshot_rows(scope="Rep", user=MANAGER, month=month)
		self.assertEqual(team[0].forecasted, 15_000)
		self.assertEqual(own[0].forecasted, 5_000)

	def test_an_in_tree_manager_reads_their_team_series_not_the_site_one(self):
		"""The leak this closes: with no explicit user the reader fell through to
		the row with an empty user, which is the whole company."""
		from crm.api.dashboard import forecast_accuracy_scope

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(MANAGER)
		scope, who, members = forecast_accuracy_scope(None)
		self.assertEqual(scope, "Team")
		self.assertEqual(who, MANAGER)
		self.assertIn(REP, members)
		self.assertNotIn(OUTSIDER, members)

	def test_a_company_wide_manager_still_reads_the_site_series(self):
		from crm.api.dashboard import forecast_accuracy_scope

		frappe.set_user("Administrator")
		self.assertEqual(forecast_accuracy_scope(None), ("Site", "", None))

	def test_a_named_rep_reads_that_reps_series(self):
		from crm.api.dashboard import forecast_accuracy_scope

		self.assertEqual(forecast_accuracy_scope(REP), ("Rep", REP, [REP]))

	def test_a_manager_with_no_reports_yet_reads_their_own_rep_series(self):
		"""No Team snapshot row is ever written for a node without reports (see
		test_no_team_row_is_written_for_a_leaf), so handing an in-tree manager
		with no subtree the Team series handed them a chart that could never
		populate. Their series is their own Rep row."""
		from crm.api.dashboard import forecast_accuracy_scope

		leaf = "metrics.leafmgr@example.com"
		if not frappe.db.exists("User", leaf):
			user = frappe.get_doc(
				{"doctype": "User", "email": leaf, "first_name": "Leaf Manager", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales Manager")
		self.make_node(leaf, "Leaf Manager")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(leaf)
		self.assertEqual(forecast_accuracy_scope(None), ("Rep", leaf, [leaf]))

	def test_an_empty_team_series_says_why_it_is_empty(self):
		"""Existing sites have no team history and none can be invented, so the
		chart has to explain itself rather than look broken."""
		from crm.api.dashboard import get_forecast_accuracy

		# Forecasting off is a different, more useful message and takes
		# precedence, so it has to be on for this one to say anything.
		was_on = frappe.db.get_single_value("FCRM Settings", "enable_forecasting")
		frappe.db.set_single_value("FCRM Settings", "enable_forecasting", 1)
		self.addCleanup(frappe.db.set_single_value, "FCRM Settings", "enable_forecasting", was_on or 0)

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(MANAGER)
		payload = get_forecast_accuracy()
		self.assertEqual(payload["data"], [])
		self.assertIn("team", payload["emptyState"].lower())
