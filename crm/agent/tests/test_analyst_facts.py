# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What the Analyst may say, worked out by code, and the check on what it did say.

The cases are the 2026-10-15 browser QA on a live site, where a 2.6B model read
correct tables and still told an admin that a quarter it had been handed was
missing, that the best month was the wrong one, and that one rep's figures were
another's. No site, no model."""

from __future__ import annotations

from datetime import date

from frappe.tests import UnitTestCase

from crm.agent import analyst, analyst_facts

TODAY = date(2026, 10, 15)


def table(key, rows, note="", error=None, facts=None, summary=None):
	metric = analyst.CATALOGUE[key]
	return {
		"key": key,
		"title": metric["title"],
		"source": "CRM",
		"columns": metric["columns"],
		"rows": rows,
		"note": note,
		"error": error,
		"facts": facts or [],
		"summary": summary or [],
	}


def won(*pairs):
	return table("won_revenue_by_month", [{"month": m, "value": v} for m, v in pairs])


Q3 = won(("2026-07", 11358307.02), ("2026-08", 4598159.90), ("2026-09", 2578053.92))
Q2 = won(("2026-04", 9911312.0), ("2026-05", 7560692.08), ("2026-06", 16103594.09))
YEAR = won(
	("2026-01", 15715599.83),
	("2026-02", 17151669.63),
	("2026-03", 9711636.15),
	("2026-04", 9911312.0),
	("2026-05", 7560692.08),
	("2026-06", 16103594.09),
	("2026-07", 11358307.02),
	("2026-08", 4598159.90),
	("2026-09", 2578053.92),
	("2026-10", 0.0),
)
REPS = table(
	"quota_attainment_by_rep",
	[
		{"rep": "Administrator", "quota": 0.0, "actual": 15634385.36, "attainment_pct": None},
		{"rep": "Ann-Mari Prins", "quota": 0.0, "actual": 31216749.05, "attainment_pct": None},
		{"rep": "Kevin Purdon", "quota": 0.0, "actual": 11413462.0, "attainment_pct": None},
		{"rep": "Bianca", "quota": 0.0, "actual": 33902.23, "attainment_pct": None},
	],
)
OWNERS = table(
	"deals_by_salesperson",
	[
		{"salesperson": "Janca Meiring", "deals": 144, "value": 13320006.0},
		{"salesperson": "Ann-Mari Prins", "deals": 89, "value": 28946451.89},
		{"salesperson": "Lilly de Villiers", "deals": 43, "value": 1920789.0},
	],
)
WON_BY_REP = table(
	"won_by_rep",
	[
		{"rep": "Ann-Mari Prins", "won": 9000000.0, "won_deals": 12, "closed_deals": 20, "win_rate_pct": 60},
		{"rep": "Janca Meiring", "won": 7000000.0, "won_deals": 30, "closed_deals": 40, "win_rate_pct": 75},
		{"rep": "Kevin Purdon", "won": 0.0, "won_deals": 0, "closed_deals": 5, "win_rate_pct": 0},
	],
)


def with_facts(*tables):
	return [{**t, "facts": analyst_facts.table_facts(t, TODAY)} for t in tables]


def ground(answer, *tables, caveats=(), history=None):
	return analyst_facts.ground_reply(answer, list(caveats), with_facts(*tables), TODAY, history)


class MonthlyFactsTest(UnitTestCase):
	def test_one_quarter_gets_its_total_and_its_best_and_worst_month(self):
		facts = analyst_facts.table_facts(Q3, TODAY)
		self.assertIn("Q3 2026 (July to September 2026): 18,534,521", facts)
		self.assertIn("Highest month: July 2026 (11,358,307)", facts)
		self.assertIn("Lowest month: September 2026 (2,578,054)", facts)

	def test_a_year_names_the_real_peak_and_leaves_the_current_month_out_of_it(self):
		facts = analyst_facts.table_facts(YEAR, TODAY)
		self.assertIn("Highest month: February 2026 (17,151,670)", facts)
		# October is fifteen days old: its R0 is not the year's worst month
		self.assertIn("Lowest month: September 2026 (2,578,054)", facts)
		self.assertTrue(any("October 2026 is month to date" in line for line in facts), facts)

	def test_complete_quarters_and_the_current_one_to_date(self):
		facts = analyst_facts.table_facts(YEAR, TODAY)
		self.assertIn("Q1 2026: 42,578,906", facts)
		self.assertIn("Q2 2026: 33,575,598", facts)
		self.assertIn("Q3 2026: 18,534,521", facts)
		self.assertIn("Q4 2026 to date: 0", facts)

	def test_a_quarter_the_window_only_clips_is_not_totalled(self):
		facts = analyst_facts.table_facts(
			won(("2026-03", 5.0), ("2026-04", 1.0), ("2026-05", 2.0), ("2026-06", 3.0)), TODAY
		)
		self.assertIn("Q2 2026: 6", facts)
		self.assertFalse(any(line.startswith("Q1 2026") for line in facts), facts)

	def test_months_before_revenue_began_are_not_the_lowest(self):
		facts = analyst_facts.table_facts(
			won(("2025-11", 0.0), ("2025-12", 4850975.6), ("2026-01", 15715599.83)), TODAY
		)
		self.assertIn("Lowest month: December 2025 (4,850,976)", facts)

	def test_growth_rates_get_the_same_facts(self):
		rows = [
			{"month": "2026-07", "value": 10.0, "change_pct": None},
			{"month": "2026-08", "value": 20.0, "change_pct": 100.0},
		]
		facts = analyst_facts.table_facts(table("growth_rates", rows), TODAY)
		self.assertIn("Highest month: August 2026 (20)", facts)

	def test_an_empty_or_unavailable_table_has_no_facts(self):
		self.assertEqual(analyst_facts.table_facts(won(), TODAY), [])
		self.assertEqual(
			analyst_facts.table_facts(table("erp_invoices_by_month", [], error="unreachable"), TODAY), []
		)


class RankingFactsTest(UnitTestCase):
	def test_reps_are_ranked_by_won_value_even_with_no_targets(self):
		facts = analyst_facts.table_facts(REPS, TODAY)
		self.assertIn(
			"Ranked by won value: 1. Ann-Mari Prins 31,216,749; 2. Administrator 15,634,385; "
			"3. Kevin Purdon 11,413,462; 4. Bianca 33,902",
			facts,
		)
		self.assertIn("No rep has a target set for this period, so attainment cannot be measured.", facts)

	def test_a_breakdown_is_ranked_by_value_with_its_total(self):
		facts = analyst_facts.table_facts(OWNERS, TODAY)
		self.assertEqual(
			facts[0],
			"Ranked by value of deals created, any outcome, not revenue: 1. Ann-Mari Prins 28,946,452; "
			"2. Janca Meiring 13,320,006; 3. Lilly de Villiers 1,920,789",
		)
		self.assertIn("Total value of deals created, any outcome, not revenue: 44,187,247", facts)

	def test_the_open_pipeline_says_what_weighting_did(self):
		pipeline = table(
			"pipeline_by_stage",
			[{"stage": "Proposal/Quotation", "deals": 462, "value": 72734990.67, "weighted": 36367495.34}],
		)
		self.assertIn(
			"462 open deals worth 72,734,991; weighted by stage probability that is 36,367,495 (50% of the value)",
			analyst_facts.table_facts(pipeline, TODAY),
		)


class GroundingTest(UnitTestCase):
	def test_a_true_sentence_is_kept_word_for_word(self):
		text = "In Q3 2026 you won R11,358,307.02 in July 2026 and R2,578,053.92 in September 2026."
		self.assertEqual(ground(text, Q3)["answer"], text)

	def test_the_computed_total_may_be_quoted_rounded(self):
		for said in ("18,534,521", "R18.5 million", "18,534,520.84"):
			with self.subTest(said=said):
				text = f"Last quarter you won {said}."
				self.assertEqual(ground(text, Q3)["answer"], text)

	def test_a_number_that_is_nowhere_in_the_figures_is_dropped(self):
		reply = ground("You won R11,358,307.02 in July 2026. Deal values range from 2,750.23 ZAR upward.", Q3)
		self.assertEqual(reply["answer"], "You won R11,358,307.02 in July 2026.")
		self.assertEqual(reply["dropped"], 1)

	def test_a_near_miss_is_a_miss(self):
		# what the model wrote for June 2026 was 16,103,914.09; the row says 16,103,594.09
		self.assertEqual(ground("June 2026 had 16,103,914.09.", Q2)["dropped"], 1)
		self.assertEqual(ground("June 2026 had 16,103,594.09.", Q2)["dropped"], 0)

	def test_another_reps_figures_under_this_reps_name_are_dropped(self):
		reply = ground(
			"Janca Meiring holds 144 deals worth 13,320,006. "
			"Lilly de Villiers holds 89 deals worth 28,946,451.89.",
			OWNERS,
		)
		self.assertEqual(reply["answer"], "Janca Meiring holds 144 deals worth 13,320,006.")

	def test_a_figure_a_fact_line_quotes_for_one_row_still_belongs_to_that_row(self):
		"""A ranking, a best or worst month and the largest deals at risk each quote one
		row's own figure. Read as totals -- which may stand beside any name -- they
		let the 2026-10-15 failure through: one rep's value under another's name."""
		risk = table(
			"deals_at_risk",
			[
				{"deal": "CRM-DEAL-1", "organization": "Acme Mining", "health_score": 10, "value": 500000.0},
				{"deal": "CRM-DEAL-2", "organization": "Beta Metals", "health_score": 20, "value": 300000.0},
			],
		)
		trend = table(
			"sales_trend",
			[
				{"month": "2026-03", "leads": 60, "deals": 45, "won_deals": 9},
				{"month": "2026-04", "leads": 70, "deals": 12, "won_deals": 4},
			],
		)
		for wrong, right, figures in (
			(
				"Lilly de Villiers holds deals worth 28,946,451.89.",
				"Ann-Mari Prins holds deals worth 28,946,451.89.",
				OWNERS,
			),
			("January 2026 brought in 17,151,670.", "February 2026 brought in 17,151,670.", YEAR),
			("August 2026 brought in 2,578,054.", "September 2026 brought in 2,578,054.", YEAR),
			("Beta Metals has 500,000 at risk.", "Acme Mining has 500,000 at risk.", risk),
			("April 2026 had 45 new deals.", "March 2026 had 45 new deals.", trend),
		):
			with self.subTest(wrong=wrong):
				self.assertEqual(ground(wrong, figures)["dropped"], 1)
				self.assertEqual(ground(right, figures)["dropped"], 0)

	def test_a_change_may_be_written_without_its_sign(self):
		growth = table("growth_rates", [{"month": "2026-03", "value": 9711636.15, "change_pct": -43.4}])
		self.assertEqual(ground("Revenue fell 43.4% in March 2026.", growth)["dropped"], 0)

	def test_a_small_percentage_is_a_figure_and_is_checked(self):
		"""Whole numbers up to 31 are skipped as days, months and small counts. A
		percentage is none of those, and a wrong 25% passed where 35% was caught."""
		growth = table(
			"growth_rates",
			[
				{"month": "2026-02", "value": 17151669.63, "change_pct": None},
				{"month": "2026-03", "value": 9711636.15, "change_pct": -43.4},
			],
		)
		adherence = table(
			"plan_adherence_by_rep",
			[{"rep": "Kevin Purdon", "planned": 8, "done": 2, "missed": 6, "adherence_pct": 25}],
		)
		self.assertEqual(ground("Revenue fell 25% in March 2026.", growth)["dropped"], 1)
		self.assertEqual(ground("Kevin Purdon kept 28% of his plan.", adherence)["dropped"], 1)
		self.assertEqual(ground("Kevin Purdon kept 28 percent of his plan.", adherence)["dropped"], 1)
		# the percentage the table holds is still quotable, and a small count still is not checked
		self.assertEqual(ground("Kevin Purdon kept 25% of his plan.", adherence)["dropped"], 0)
		self.assertEqual(ground("Kevin Purdon did 3 of his visits.", adherence)["dropped"], 0)

	def test_years_quarters_and_small_counts_are_not_checked(self):
		self.assertEqual(ground("Over the 3 months of Q3 2026 sales slowed.", Q3)["dropped"], 0)

	def test_a_period_the_figures_cover_is_never_called_missing(self):
		reply = ground(
			"Q2 2026 data is not available, so a comparison cannot be made.",
			Q3,
			Q2,
			caveats=["The figures only cover July 2026 to September 2026; May 2026 is missing."],
		)
		self.assertEqual(reply["dropped"], 2)
		self.assertEqual(reply["caveats"], [])

	def test_a_period_outside_the_figures_may_be_called_missing(self):
		text = "There is no data for January 2024."
		self.assertEqual(ground(text, Q3)["answer"], text)

	def test_an_unreachable_erp_may_be_reported_for_a_month_the_crm_covers(self):
		erp = table("erp_invoices_by_month", [], error="unreachable")
		text = "Invoice data for August 2026 is not available because the ERP could not be reached."
		self.assertEqual(ground(text, Q3, erp)["answer"], text)

	def test_a_best_month_must_be_the_best_month(self):
		# January's number, quoted right, under a claim that was wrong: February was the peak
		self.assertEqual(ground("Sales peaked in January 2026 at 15,715,599.83.", YEAR)["dropped"], 1)
		self.assertEqual(ground("Sales peaked in February 2026 at 17,151,669.63.", YEAR)["dropped"], 0)
		self.assertEqual(ground("June 2026 was the highest single month.", YEAR)["dropped"], 1)

	def test_the_current_month_is_not_the_worst_one(self):
		self.assertEqual(ground("October 2026 was the lowest month.", YEAR)["dropped"], 1)
		self.assertEqual(ground("September 2026 was the lowest month at 2,578,053.92.", YEAR)["dropped"], 0)

	def test_no_change_is_measured_against_a_month_that_has_barely_started(self):
		self.assertEqual(
			ground("October 2026 shows a 100% decrease from September 2026.", YEAR)["dropped"], 1
		)
		text = "October 2026 is month to date."
		self.assertEqual(ground(text, YEAR)["answer"], text)

	def test_a_ranking_word_about_people_is_not_a_month_claim(self):
		text = "Ann-Mari Prins has the highest won value, 31,216,749.05."
		self.assertEqual(ground(text, REPS)["answer"], text)

	def test_a_follow_up_may_quote_what_the_last_answer_said(self):
		"""Caught live: "Q2 was better than Q3" was right, and Q3's total came from the
		turn before -- the tables of this turn hold only Q2."""
		history = [
			{"role": "user", "content": "How much did we win last quarter?"},
			{"role": "assistant", "content": "You won 18,534,521 ZAR in Q3 2026."},
		]
		text = "Q2 2026 brought in 33,575,598 ZAR, better than the 18,534,521 ZAR of Q3 2026."
		self.assertEqual(ground(text, Q2, history=history)["answer"], text)
		# what the admin typed is not a figure anyone computed
		asked = [{"role": "user", "content": "Was it more than 18,534,521?"}]
		self.assertEqual(ground(text, Q2, history=asked)["dropped"], 1)

	def test_the_months_before_the_history_may_be_called_missing(self):
		text = "There is no data before December 2025."
		self.assertEqual(ground(text, won(("2025-12", 4850975.6)))["answer"], text)

	def test_a_year_with_no_data_may_be_called_missing_next_to_a_covered_month(self):
		# caught live on LFM2.5-24B: a true sentence, dropped for naming December 2025
		text = "There are no figures for 2024; the history starts in December 2025."
		self.assertEqual(ground(text, won(("2025-12", 4850975.6)))["answer"], text)
		self.assertEqual(ground("December 2025 is not available.", won(("2025-12", 1.0)))["dropped"], 1)

	def test_a_total_beside_the_names_it_sums_is_not_misattributed(self):
		"""Caught live on LFM2.5-24B: the 336 is the at-risk total, and the summary's
		"- No activity: 336 deals" line made it look like a figure owned by a row."""
		rows = [
			{
				"deal": f"D{i}",
				"organization": "Org",
				"owner": owner,
				"health_score": 5,
				"value": 10.0,
				"reasons": "No activity",
			}
			for owner, count in (("Janca Meiring", 200), ("Ann-Mari Prins", 136))
			for i in range(count)
		]
		risk = table("deals_at_risk", rows, summary=analyst.summarise_at_risk(rows))
		text = "Of the 336 deals at risk, Janca Meiring holds 200 and Ann-Mari Prins 136."
		self.assertEqual(ground(text, risk)["answer"], text)
		self.assertEqual(ground("Janca Meiring holds 136 at-risk deals.", risk)["dropped"], 1)

	def test_breaking_down_is_not_a_drop(self):
		text = "The figures run from January 2026 to October 2026 but do not break down sales by customer."
		self.assertEqual(ground(text, YEAR)["answer"], text)

	def test_internal_wording_does_not_reach_the_admin(self):
		reply = ground(
			"You won R11,358,307.02 in July 2026. The figures block only contains Q3. Attainment_pct is null for all reps.",
			Q3,
		)
		self.assertEqual(reply["answer"], "You won R11,358,307.02 in July 2026.")

	def test_an_answer_with_nothing_left_says_so_instead_of_going_blank(self):
		reply = ground("Deal values range from 2,750.23 to 57,721,677.69 ZAR.", REPS)
		self.assertEqual(reply["answer"], analyst_facts.FALLBACK_ANSWER)

	def test_highlights_are_the_computed_facts(self):
		tables = with_facts(Q3, OWNERS)
		highlights = analyst_facts.highlights(tables)
		self.assertEqual(highlights[0], "Q3 2026 (July to September 2026): 18,534,521")
		self.assertLessEqual(len(highlights), analyst_facts.MAX_HIGHLIGHTS)


class CoverageTest(UnitTestCase):
	def test_months_before_the_data_starts_are_dropped_and_the_note_says_why(self):
		rows, note = analyst_facts.trim_to_coverage(
			[{"month": "2025-11", "value": 0.0}, {"month": "2025-12", "value": 4850975.6}], "2025-12"
		)
		self.assertEqual([row["month"] for row in rows], ["2025-12"])
		self.assertIn("December 2025", note)
		self.assertIn("no data", note)

	def test_nothing_to_trim_says_nothing(self):
		rows, note = analyst_facts.trim_to_coverage([{"month": "2026-01", "value": 1.0}], "2025-12")
		self.assertEqual(len(rows), 1)
		self.assertEqual(note, "")

	def test_the_figures_say_where_the_history_starts(self):
		messages = analyst.build_answer_messages(
			"How did we do in 2024?",
			[],
			{"from_date": "2024-01-01", "to_date": "2024-12-31", "data_from": "2025-12"},
		)
		self.assertIn("December 2025", messages[0]["content"])


class RankedByWonValueTest(UnitTestCase):
	def test_the_ranking_states_its_measure_and_carries_the_win_rate(self):
		facts = analyst_facts.table_facts(WON_BY_REP, TODAY)
		self.assertEqual(
			facts[0],
			"Ranked by won value in the period: 1. Ann-Mari Prins 9,000,000 (60% win rate, 12 of 20 closed); "
			"2. Janca Meiring 7,000,000 (75% win rate, 30 of 40 closed); "
			"3. Kevin Purdon 0 (0% win rate, 0 of 5 closed)",
		)
		self.assertIn("Total won value in the period: 16,000,000", facts)
		self.assertIn("Overall win rate: 65% (42 won of 65 closed)", facts)

	def test_the_measure_is_among_the_lines_on_screen(self):
		self.assertIn("won value", analyst_facts.highlights(with_facts(WON_BY_REP))[0])

	def test_a_rep_with_no_closed_deals_has_no_win_rate(self):
		rows = [{"rep": "New Rep", "won": 0.0, "won_deals": 0, "closed_deals": 0, "win_rate_pct": None}]
		facts = analyst_facts.table_facts(table("won_by_rep", rows), TODAY)
		self.assertIn("1. New Rep 0 (no closed deals)", facts[0])
		self.assertFalse([line for line in facts if line.startswith("Overall win rate")])

	def test_ranked_rows_sort_the_way_the_ranking_reads(self):
		"""Prod's table ran by deal count under a ranking by value."""
		self.assertEqual(
			[row["salesperson"] for row in analyst_facts.rank_rows("deals_by_salesperson", OWNERS["rows"])],
			["Ann-Mari Prins", "Janca Meiring", "Lilly de Villiers"],
		)
		rows = [{"rep": "A", "actual": None}, {"rep": "B", "actual": 5.0}]
		self.assertEqual(
			[row["rep"] for row in analyst_facts.rank_rows("quota_attainment_by_rep", rows)], ["B", "A"]
		)
		unranked = [{"stage": "b"}, {"stage": "a"}]
		self.assertEqual(analyst_facts.rank_rows("pipeline_by_stage", unranked), unranked)

	def test_the_narrative_may_not_crown_someone_the_ranking_does_not(self):
		self.assertEqual(ground("Janca Meiring is your best salesperson.", WON_BY_REP)["dropped"], 1)
		self.assertEqual(ground("Ann-Mari Prins is your top rep.", WON_BY_REP)["dropped"], 0)
		self.assertEqual(ground("Ann-Mari Prins leads, ahead of Janca Meiring.", WON_BY_REP)["dropped"], 0)

	def test_the_best_win_rate_is_a_different_claim_from_the_best_rep(self):
		text = "Janca Meiring has the highest win rate, at 75%."
		self.assertEqual(ground(text, WON_BY_REP)["answer"], text)


# The months prod's narrative called growth, with today in the month after them.
FALLING = won(
	("2026-06", 16103594.09),
	("2026-07", 11358307.02),
	("2026-08", 4598159.90),
	("2026-09", 2578053.92),
	("2026-10", 0.0),
)
FALLING_TODAY = date(2026, 11, 2)


def series(*values, start=1):
	return [(f"2026-{start + i:02d}", value) for i, value in enumerate(values)]


def ground_at(answer, *tables, today=FALLING_TODAY, question="", caveats=()):
	facted = [{**t, "facts": analyst_facts.table_facts(t, today)} for t in tables]
	return analyst_facts.ground_reply(answer, list(caveats), facted, today, question=question)


class TrendDirectionTest(UnitTestCase):
	def direction(self, *values, today=date(2026, 12, 15)):
		return analyst_facts.trend_direction(series(*values), today)

	def test_a_steady_fall(self):
		trend = analyst_facts.trend_direction(
			[(r["month"], r["value"]) for r in FALLING["rows"]], FALLING_TODAY
		)
		self.assertEqual(trend["direction"], "down")
		self.assertEqual(trend["first"], ("2026-06", 16103594.09))
		self.assertEqual(trend["last"], ("2026-10", 0.0))
		self.assertEqual(trend["peak"], ("2026-06", 16103594.09))
		self.assertEqual(trend["falls"], 4)

	def test_a_steady_rise(self):
		trend = self.direction(100, 200, 300)
		self.assertEqual(trend["direction"], "up")
		self.assertEqual(trend["rises"], 2)

	def test_the_current_month_does_not_set_the_direction(self):
		"""Two days of November are not a collapse, nor an end point."""
		self.assertEqual(self.direction(100, 200, 5, today=date(2026, 3, 2))["direction"], "up")

	def test_months_before_revenue_began_are_not_a_low_start(self):
		self.assertEqual(self.direction(0, 0, 500, 400, 300)["direction"], "down")

	def test_a_change_inside_the_band_is_flat(self):
		self.assertEqual(self.direction(1000, 1200, 1030)["direction"], "flat")
		self.assertEqual(self.direction(1000, 1000)["direction"], "flat")

	def test_a_rise_that_has_since_fallen_three_months_running_is_mixed(self):
		"""2 -> 3 is a rise; 2, 20, 16, 15, 14, 3 is not a business that is growing."""
		self.assertEqual(self.direction(2, 20, 16, 15, 14, 3)["direction"], "mixed")
		self.assertEqual(self.direction(100, 90, 95, 110, 120)["direction"], "up")

	def test_too_few_points(self):
		self.assertEqual(self.direction(500)["direction"], "unclear")
		self.assertEqual(self.direction(0, 0, 0)["direction"], "unclear")
		self.assertEqual(analyst_facts.trend_direction([], TODAY)["direction"], "unclear")


class TrendFactTest(UnitTestCase):
	def line(self, tbl, today=FALLING_TODAY):
		return next(line for line in analyst_facts.table_facts(tbl, today) if line.startswith("Direction:"))

	def test_the_direction_is_a_fact_the_model_is_handed(self):
		self.assertEqual(
			self.line(FALLING),
			"Direction: Revenue from won deals fell from 16,103,594 in June 2026 to 0 in October 2026, "
			"down 4 months running.",
		)

	def test_it_survives_the_cap_on_lines_shown(self):
		facted = [{**YEAR, "facts": analyst_facts.table_facts(YEAR, TODAY)}]
		self.assertTrue(any(line.startswith("Direction:") for line in analyst_facts.highlights(facted)))

	def test_a_partial_month_is_named_as_left_out(self):
		self.assertIn("October 2026 is month to date and not counted", self.line(YEAR, TODAY))

	def test_flat_mixed_and_too_few_say_so(self):
		flat = won(("2026-06", 1000.0), ("2026-07", 1020.0))
		self.assertIn("held roughly level", self.line(flat))
		mixed = won(*series(2.0, 20.0, 16.0, 15.0, 14.0, 3.0))
		self.assertIn("ended above where it started", self.line(mixed))
		self.assertIn("down 4 months running", self.line(mixed))
		one = won(("2026-10", 1000.0))
		self.assertIn("Not enough complete months", self.line(one))

	def test_a_forward_series_has_no_direction(self):
		forward = table(
			"forecast_by_month", [{"month": "2026-12", "value": 5.0}, {"month": "2027-01", "value": 9.0}]
		)
		self.assertFalse(
			[l for l in analyst_facts.table_facts(forward, FALLING_TODAY) if l.startswith("Direction:")]
		)

	def test_the_answer_prompt_says_the_question_does_not_set_the_direction(self):
		self.assertIn("Direction", analyst.ANSWER_SYSTEM_PROMPT)
		self.assertIn("whatever the question assumes", analyst.ANSWER_SYSTEM_PROMPT)


class TrendClaimTest(UnitTestCase):
	FACT = "Revenue from won deals fell from 16,103,594 in June 2026 to 0 in October 2026, down 4 months running."

	def test_prods_sentence_is_replaced_by_the_computed_one(self):
		reply = ground_at("Revenue grew to a total of 42,198,807.", FALLING)
		self.assertEqual(reply["answer"], self.FACT)
		self.assertEqual(reply["dropped"], 1)

	def test_a_question_about_growth_does_not_coax_grew(self):
		for answer in ("Yes, revenue has grown steadily.", "Yes.", "Sales are growing nicely."):
			with self.subTest(answer=answer):
				reply = ground_at(answer, FALLING, question="Has revenue grown this year?")
				self.assertEqual(reply["answer"], self.FACT)

	def test_a_growth_question_answered_without_a_direction_gets_one(self):
		text = "The total for the period is 34,638,115."
		reply = ground_at(text, FALLING, question="Are we growing?")
		self.assertEqual(reply["answer"], f"{self.FACT} {text}")

	def test_an_unrelated_question_is_not_handed_a_direction(self):
		text = "September 2026 brought in 2,578,053.92."
		self.assertEqual(ground_at(text, FALLING, question="What did we win?")["answer"], text)

	def test_the_true_claim_stands(self):
		text = "Revenue fell every month after June 2026."
		reply = ground_at(text, FALLING, question="Are we growing?")
		self.assertEqual(reply["answer"], text)
		self.assertEqual(reply["dropped"], 0)
		rising = won(("2026-07", 100.0), ("2026-08", 200.0), ("2026-09", 400.0))
		self.assertEqual(ground_at("Revenue grew.", rising)["answer"], "Revenue grew.")

	def test_a_fall_claimed_against_a_rise_is_replaced_too(self):
		rising = won(("2026-07", 100.0), ("2026-08", 200.0), ("2026-09", 400.0))
		reply = ground_at("Revenue declined over the period.", rising)
		self.assertEqual(
			reply["answer"],
			"Revenue from won deals rose from 100 in July 2026 to 400 in September 2026, up 2 months running.",
		)

	def test_flat_and_too_few_reject_both_directions(self):
		flat = won(("2026-07", 1000.0), ("2026-08", 1010.0), ("2026-09", 1020.0))
		one = won(("2026-10", 1000.0))
		for tbl in (flat, one):
			for claim in ("Revenue grew.", "Revenue fell."):
				with self.subTest(claim=claim):
					self.assertEqual(ground_at(claim, tbl)["dropped"], 1)
					self.assertNotEqual(ground_at(claim, tbl)["answer"], claim)

	def test_a_claim_about_named_months_is_checked_on_those_months(self):
		"""May to June really did rise, in a year that fell."""
		text = "Revenue grew from May 2026 to June 2026."
		self.assertEqual(ground(text, YEAR)["answer"], text)
		self.assertEqual(ground("Revenue grew in June 2026.", YEAR)["answer"], "Revenue grew in June 2026.")
		self.assertEqual(ground("Revenue grew in July 2026.", YEAR)["dropped"], 1)
		self.assertEqual(ground("Revenue fell from May 2026 to June 2026.", YEAR)["dropped"], 1)
		self.assertEqual(ground("Revenue has grown since June 2026.", YEAR)["dropped"], 1)

	def test_a_sentence_telling_both_halves_is_left_alone(self):
		text = "Revenue rose to a peak in February 2026, then fell."
		self.assertEqual(ground(text, YEAR)["answer"], text)

	def test_a_denied_rise_is_not_a_claim_of_one(self):
		for text in ("Revenue did not grow.", "There was no growth in revenue.", "Revenue has not risen."):
			with self.subTest(text=text):
				self.assertEqual(ground_at(text, FALLING)["answer"], text)

	def test_a_table_name_is_not_a_claim(self):
		text = "The growth rates are shown below."
		self.assertEqual(ground_at(text, FALLING)["answer"], text)
		self.assertEqual(ground_at("Let me break down the revenue.", FALLING)["dropped"], 0)

	def test_other_subjects_are_not_held_to_the_revenue_direction(self):
		for text in ("New leads grew.", "The pipeline grew.", "Ann-Mari Prins improved."):
			with self.subTest(text=text):
				self.assertEqual(ground_at(text, FALLING, REPS)["answer"], text)

	def test_each_series_answers_for_its_own_claims(self):
		invoices = table(
			"erp_invoices_by_month",
			[
				{"month": "2026-07", "invoiced": 100.0, "invoices": 2},
				{"month": "2026-08", "invoiced": 300.0, "invoices": 3},
			],
		)
		text = "Invoicing grew."
		self.assertEqual(ground_at(text, FALLING, invoices)["answer"], text)
		self.assertEqual(ground_at("Revenue grew.", FALLING, invoices)["answer"], self.FACT)

	def test_the_replacement_appears_once(self):
		reply = ground_at("Revenue grew. Sales rose again.", FALLING)
		self.assertEqual(reply["answer"], self.FACT)
		self.assertEqual(reply["dropped"], 2)

	def test_a_caveat_is_dropped_not_replaced(self):
		reply = ground_at("Revenue fell.", FALLING, caveats=["Revenue is growing."])
		self.assertEqual(reply["caveats"], [])
		self.assertEqual(reply["dropped"], 1)
