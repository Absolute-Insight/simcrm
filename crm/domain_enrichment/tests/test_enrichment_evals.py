# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Tests for the golden-set harness -- not for the model.

No endpoint is contacted. What is asserted is that the scoring distinguishes the
five outcomes correctly, and that a run which did not happen cannot be read as a
run that went well. That last property is the reason the file exists: with no
endpoint every field comes back blank, every abstention case scores ``abstained``,
and a naive report would show a model abstaining flawlessly while having made no
calls at all.
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import UnitTestCase

from crm.agent.errors import AgentUnavailable
from crm.agent.schemas import SiteFacts
from crm.domain_enrichment.evals import cases as case_data
from crm.domain_enrichment.evals import runner
from crm.domain_enrichment.evals.cases import CASES, Case

CFG = frappe._dict(model="test-model", base_url="http://localhost:1/v1", enabled=1)


class ScoringTest(UnitTestCase):
	def test_the_expected_value_is_correct(self):
		self.assertEqual(runner.score_field("company_name", "Acme", "Acme", []), runner.CORRECT)

	def test_case_differences_are_not_counted_as_wrong(self):
		self.assertEqual(runner.score_field("company_name", "Acme", "ACME", []), runner.CORRECT)

	def test_a_different_value_is_wrong(self):
		self.assertEqual(runner.score_field("company_name", "Acme", "Globex", []), runner.WRONG)

	def test_a_blank_where_something_was_expected_is_a_miss_not_an_error(self):
		"""The safe failure: the field stays as blank as the rules left it."""
		self.assertEqual(runner.score_field("company_name", "Acme", "", []), runner.MISSED)

	def test_a_blank_where_blank_was_expected_is_abstention(self):
		self.assertEqual(runner.score_field("company_name", "", "", []), runner.ABSTAINED)

	def test_a_value_where_blank_was_expected_is_hallucination(self):
		"""The outcome a hit rate hides, and the one that writes fiction to a record."""
		self.assertEqual(runner.score_field("company_name", "", "Invented Ltd", []), runner.HALLUCINATED)

	def test_whitespace_counts_as_blank_on_both_sides(self):
		self.assertEqual(runner.score_field("company_name", "", "   ", []), runner.ABSTAINED)
		self.assertEqual(runner.score_field("company_name", "Acme", "  ", []), runner.MISSED)

	# These pass "" for `expected`, which is what the real cases carry: a case
	# wanting a description declares `description_must_mention`, not a sentence.
	# An earlier version of these tests passed "x" and so exercised a path no case
	# reaches -- it scored every correct description as an invention and the suite
	# stayed green.
	def test_a_description_about_the_right_thing_is_correct(self):
		self.assertEqual(
			runner.score_field("description", "", "We do medical billing for clinics.", ["billing"]),
			runner.CORRECT,
		)

	def test_a_description_about_something_else_is_wrong(self):
		self.assertEqual(
			runner.score_field("description", "", "A premium coffee subscription.", ["billing"]),
			runner.WRONG,
		)

	def test_a_missing_description_that_was_wanted_is_a_miss(self):
		self.assertEqual(runner.score_field("description", "", "", ["billing"]), runner.MISSED)

	def test_a_description_where_none_was_wanted_is_hallucination(self):
		"""No `must_mention` and no expectation means the page had nothing to describe."""
		self.assertEqual(runner.score_field("description", "", "Some company.", []), runner.HALLUCINATED)


class ScoredFieldsTest(UnitTestCase):
	"""Which fields a case makes a claim about at all."""

	def test_a_case_wanting_a_description_scores_it(self):
		case = case_data.by_name("clinic_saas_says_everything")
		self.assertIn("description", runner.scored_fields(case))

	def test_a_field_the_case_says_nothing_about_is_not_scored(self):
		"""Both a product name and a blank are defensible on the login-wall case."""
		case = case_data.by_name("login_wall_reveals_only_a_product_name")
		self.assertNotIn("company_name", runner.scored_fields(case))
		self.assertIn("industry", runner.scored_fields(case))

	def test_wanting_a_description_does_not_drag_in_the_other_fields(self):
		"""The bug this replaced: the condition ignored `name`, so any case with
		description_must_mention scored all three -- and a case that never mentions
		industry was marked as having invented one."""
		case = Case(name="only-desc", text="x", expected={}, description_must_mention=["thing"])
		self.assertEqual(runner.scored_fields(case), ["description"])


class HarmfulOutcomesTest(UnitTestCase):
	def test_only_wrong_and_hallucinated_are_harmful(self):
		"""`missed` must never be averaged in with them: a cautious model would look
		as bad as an inventive one, which inverts the thing being optimised."""
		self.assertEqual(set(runner.HARMFUL), {runner.WRONG, runner.HALLUCINATED})
		self.assertNotIn(runner.MISSED, runner.HARMFUL)


class ReportHonestyTest(UnitTestCase):
	"""A zero that means "did not run" reads exactly like a zero that means
	"nothing went wrong". These make the two impossible to confuse."""

	def test_an_endpoint_that_never_answers_reports_that_nothing_was_measured(self):
		with mock.patch.object(runner.client, "complete", side_effect=AgentUnavailable("refused")):
			results = runner.run(cfg=CFG)
		report = runner.format_report(results, CFG)
		self.assertIn("DID NOT RUN", report)
		self.assertIn("Nothing was measured", report)

	def test_a_dead_endpoint_is_not_credited_with_perfect_abstention(self):
		"""The failure this harness is arranged to prevent. Every field comes back
		blank, so every abstention case would score `abstained` -- a model that made
		no calls at all must not read as one that answered carefully."""
		with mock.patch.object(runner.client, "complete", side_effect=AgentUnavailable("refused")):
			report = runner.format_report(runner.run(cfg=CFG), CFG)
		self.assertNotIn(
			"abstained", report.split("Nothing was measured")[0].lower().replace("did not run", "")
		)
		self.assertNotIn("harmful of", report)

	def test_a_run_that_worked_reports_counts(self):
		with mock.patch.object(runner.client, "complete", return_value=SiteFacts(company_name="VitalLedger")):
			report = runner.format_report(runner.run(cfg=CFG), CFG)
		self.assertIn("fields scored", report)
		self.assertNotIn("Nothing was measured", report)

	def test_the_harmful_count_is_the_headline_not_the_correct_count(self):
		with mock.patch.object(
			runner.client, "complete", return_value=SiteFacts(company_name="Invented Ltd")
		):
			report = runner.format_report(runner.run(cfg=CFG), CFG)
		self.assertIn("harmful of", report)
		self.assertIn("hallucinated", report)

	def test_harmful_answers_are_named_so_they_can_be_looked_at(self):
		with mock.patch.object(
			runner.client, "complete", return_value=SiteFacts(company_name="Invented Ltd")
		):
			report = runner.format_report(runner.run(cfg=CFG), CFG)
		self.assertIn("Invented Ltd", report)

	def test_a_partial_outage_still_says_so(self):
		"""Some cases answering does not make the missing ones fine."""
		answers = [SiteFacts(company_name="VitalLedger"), AgentUnavailable("refused")]

		def flaky(*_args, **_kwargs):
			value = answers.pop(0) if answers else SiteFacts()
			if isinstance(value, Exception):
				raise value
			return value

		with mock.patch.object(runner.client, "complete", side_effect=flaky):
			report = runner.format_report(runner.run(cfg=CFG), CFG)
		self.assertIn("DID NOT RUN", report)


class GoldenSetShapeTest(UnitTestCase):
	"""The set itself has to keep the property it was built for."""

	def test_it_contains_abstention_cases(self):
		"""Without these the set rewards a model for always answering."""
		abstain = [c for c in CASES if any(v == "" for v in c.expected.values())]
		self.assertGreaterEqual(len(abstain), 3)

	def test_every_expected_industry_is_in_the_offered_vocabulary(self):
		"""An expected industry outside the list is unreachable -- the fallback
		discards anything not offered, so the case could never be scored correct."""
		for case in CASES:
			want = case.expected.get("industry")
			if want:
				with self.subTest(case=case.name):
					self.assertIn(want, case_data.INDUSTRIES)

	def test_case_names_are_unique(self):
		names = [c.name for c in CASES]
		self.assertEqual(len(names), len(set(names)))

	def test_a_scored_description_says_what_it_must_mention(self):
		for case in CASES:
			if case.expected.get("description") == "":
				continue
			if case.description_must_mention:
				continue
			with self.subTest(case=case.name):
				self.assertNotIn("description", case.expected)

	def test_by_name_finds_a_case_and_raises_otherwise(self):
		self.assertIsInstance(case_data.by_name(CASES[0].name), Case)
		with self.assertRaises(KeyError):
			case_data.by_name("no such case")
