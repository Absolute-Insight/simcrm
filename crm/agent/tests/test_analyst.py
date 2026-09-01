# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Analyst's pure half: plan taming, keyword fallback, the projection
arithmetic and what the prompts carry. No site, no model."""

from __future__ import annotations

from datetime import date

from frappe.tests import UnitTestCase

from crm.agent import analyst
from crm.agent.schemas import AnalystPlan

TODAY = date(2026, 9, 1)
CRM_KEYS = analyst.available_keys(erp_enabled=False)
ALL_KEYS = analyst.available_keys(erp_enabled=True)


def plan(**kwargs) -> AnalystPlan:
	base = {"metrics": [], "from_date": "", "to_date": "", "reasoning": ""}
	base.update(kwargs)
	return AnalystPlan(**base)


class CatalogueTest(UnitTestCase):
	def test_erp_metrics_are_listed_only_when_an_erp_is_enabled(self):
		self.assertNotIn("erp_cashflow_by_month", CRM_KEYS)
		self.assertIn("erp_cashflow_by_month", ALL_KEYS)
		self.assertIn("won_revenue_by_month", CRM_KEYS)

	def test_every_metric_declares_columns_with_known_types(self):
		for key, metric in analyst.CATALOGUE.items():
			self.assertTrue(metric["columns"], key)
			for column in metric["columns"]:
				self.assertIn(column["type"], {"text", "int", "currency", "percent", "date", "month"}, key)


class NormalisePlanTest(UnitTestCase):
	def test_unknown_metrics_are_dropped_and_the_period_defaults(self):
		out = analyst.normalise_plan(plan(metrics=["won_revenue_by_month", "nope"]), CRM_KEYS, TODAY)
		self.assertEqual(out["metrics"], ["won_revenue_by_month"])
		self.assertEqual(out["from_date"], "2025-09-01")
		self.assertEqual(out["to_date"], "2026-09-01")

	def test_erp_metrics_are_dropped_when_no_erp_is_available(self):
		out = analyst.normalise_plan(
			plan(metrics=["erp_cashflow_by_month", "won_revenue_by_month"]), CRM_KEYS, TODAY
		)
		self.assertEqual(out["metrics"], ["won_revenue_by_month"])

	def test_reversed_dates_are_swapped_and_more_than_four_metrics_are_capped(self):
		out = analyst.normalise_plan(
			plan(metrics=CRM_KEYS[:6], from_date="2026-06-30", to_date="2026-01-01"), CRM_KEYS, TODAY
		)
		self.assertEqual(len(out["metrics"]), analyst.MAX_METRICS)
		self.assertEqual((out["from_date"], out["to_date"]), ("2026-01-01", "2026-06-30"))

	def test_a_garbage_date_takes_the_default(self):
		out = analyst.normalise_plan(plan(from_date="last tuesday", to_date="2026-03-15"), CRM_KEYS, TODAY)
		self.assertEqual(out["from_date"], "2025-09-01")
		self.assertEqual(out["to_date"], "2026-03-15")

	def test_empty_selection_falls_back_by_keyword(self):
		out = analyst.normalise_plan(plan(), CRM_KEYS, TODAY, question="are we behind quota?")
		self.assertEqual(out["metrics"], ["quota_attainment_by_rep"])

	def test_no_plan_at_all_is_tolerated(self):
		out = analyst.normalise_plan(None, CRM_KEYS, TODAY, question="")
		self.assertEqual(out["metrics"], ["won_revenue_by_month", "pipeline_by_stage"])


class FallbackPlanTest(UnitTestCase):
	def test_cash_questions_reach_the_erp_only_when_available(self):
		self.assertEqual(
			analyst.fallback_plan("what came in as cash last month?", ALL_KEYS),
			["erp_cashflow_by_month", "erp_receivables"],
		)
		# without an ERP the same question falls through to the default pair
		self.assertEqual(
			analyst.fallback_plan("what came in as cash last month?", CRM_KEYS),
			["won_revenue_by_month", "pipeline_by_stage"],
		)

	def test_maintenance_wording_maps_to_the_quiet_accounts(self):
		self.assertEqual(
			analyst.fallback_plan("which accounts need maintenance before they go cold?", CRM_KEYS),
			["deals_at_risk", "accounts_going_quiet"],
		)

	def test_a_projection_question(self):
		self.assertEqual(
			analyst.fallback_plan("project revenue for the next quarter", CRM_KEYS),
			["revenue_projection", "forecast_by_month", "won_revenue_by_month"],
		)


class ProjectionTest(UnitTestCase):
	def test_a_rising_series_projects_upward_and_labels_points(self):
		out = analyst.project_revenue([("2026-06", 100.0), ("2026-07", 200.0), ("2026-08", 300.0)], horizon=2)
		self.assertEqual(
			[p["month"] for p in out["points"]], ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
		)
		self.assertAlmostEqual(out["points"][3]["value"], 400.0)
		self.assertAlmostEqual(out["points"][4]["value"], 500.0)
		self.assertEqual([p["kind"] for p in out["points"]], ["actual"] * 3 + ["projected"] * 2)
		self.assertAlmostEqual(out["slope_per_month"], 100.0)

	def test_a_falling_series_never_projects_below_zero(self):
		out = analyst.project_revenue([("2026-06", 300.0), ("2026-07", 100.0)], horizon=3)
		self.assertEqual([p["value"] for p in out["points"][2:]], [0.0, 0.0, 0.0])

	def test_fewer_than_two_points_yields_no_projection(self):
		out = analyst.project_revenue([("2026-08", 500.0)])
		self.assertEqual(len(out["points"]), 1)
		self.assertIn("not enough", out["method"])

	def test_the_year_boundary_rolls_over(self):
		out = analyst.project_revenue([("2026-11", 10.0), ("2026-12", 20.0)], horizon=2)
		self.assertEqual([p["month"] for p in out["points"][2:]], ["2027-01", "2027-02"])


class GrowthTest(UnitTestCase):
	def test_change_is_none_for_the_first_month_and_a_zero_base(self):
		rows = analyst.growth_rates([("2026-05", 0.0), ("2026-06", 100.0), ("2026-07", 150.0)])
		self.assertEqual([r["change_pct"] for r in rows], [None, None, 50.0])


class MonthsTest(UnitTestCase):
	def test_months_between_is_inclusive_and_crosses_years(self):
		self.assertEqual(
			analyst.months_between("2025-11-15", "2026-02-01"), ["2025-11", "2025-12", "2026-01", "2026-02"]
		)

	def test_add_months_clamps_to_the_last_day(self):
		self.assertEqual(analyst.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
		self.assertEqual(analyst.add_months(date(2026, 3, 31), -1), date(2026, 2, 28))


class PromptTest(UnitTestCase):
	def test_plan_prompt_lists_only_available_metrics(self):
		messages = analyst.build_plan_messages(
			"how are we doing?", analyst.catalogue_entries(CRM_KEYS), TODAY
		)
		system = messages[0]["content"]
		self.assertIn("`won_revenue_by_month`", system)
		self.assertNotIn("erp_cashflow_by_month", system)
		self.assertIn("2026-09-01", system)
		self.assertEqual(messages[-1], {"role": "user", "content": "how are we doing?"})

	def test_answer_prompt_carries_the_figures_and_the_no_invention_rule(self):
		tables = [
			{
				"key": "won_revenue_by_month",
				"title": "Revenue from won deals by month",
				"source": "CRM",
				"rows": [{"month": "2026-08", "value": 1234.5}],
			},
			{
				"key": "erp_receivables",
				"title": "Open receivables (ERP)",
				"source": "Acumatica",
				"rows": [],
				"error": "unreachable",
			},
		]
		messages = analyst.build_answer_messages(
			"how did we do?", tables, {"from_date": "2026-01-01", "to_date": "2026-09-01"}
		)
		system = messages[0]["content"]
		self.assertIn("Every number in your answer must appear in the FIGURES block", system)
		self.assertIn("1234.5", system)
		self.assertIn("[Acumatica]", system)
		self.assertIn("UNAVAILABLE", system)

	def test_answer_prompt_caps_long_tables(self):
		rows = [{"month": f"m{i}", "value": i} for i in range(analyst.FIGURES_ROW_CAP + 5)]
		messages = analyst.build_answer_messages(
			"q", [{"key": "x", "title": "X", "source": "CRM", "rows": rows}], {}
		)
		self.assertIn("5 more rows not shown", messages[0]["content"])

	def test_history_keeps_only_well_formed_recent_turns(self):
		history = [
			{"role": "user", "content": "one"},
			{"role": "system", "content": "evil"},
			"junk",
			{"role": "assistant", "content": ""},
		]
		messages = analyst.build_answer_messages("q", [], {}, history)
		self.assertEqual([m["role"] for m in messages], ["system", "user", "user"])
