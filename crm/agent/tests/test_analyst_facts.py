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
			"Ranked by deal value: 1. Ann-Mari Prins 28,946,452; 2. Janca Meiring 13,320,006; 3. Lilly de Villiers 1,920,789",
		)
		self.assertIn("Total deal value: 44,187,247", facts)

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

	def test_a_change_may_be_written_without_its_sign(self):
		growth = table("growth_rates", [{"month": "2026-03", "value": 9711636.15, "change_pct": -43.4}])
		self.assertEqual(ground("Revenue fell 43.4% in March 2026.", growth)["dropped"], 0)

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
