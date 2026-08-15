# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deal-health scoring tests — pure feature dicts in, scored verdicts out.

The score is a transparent heuristic: every deduction is attributed to a named
factor, and the factors always account exactly for the distance from 100. The
suite pins monotonicity (worse inputs never raise the score) and the
attribution invariant rather than blessing specific magic numbers.

The forward-looking factors get their own class. They are the ones that have to
fire while a deal can still be saved -- a factor that only reports elapsed time
is a post-mortem, and this tier is not supposed to be writing post-mortems.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.agent.predict import CLOSE_HORIZON_DAYS, _stage_median_days, get_deal_health, score_deal

HEALTHY = {
	"idle_days": 1,
	"days_in_stage": 5,
	"stage": "Qualification",
	"stage_median_days": 10,
	"stage_probability": 20,
	"days_to_close": 30,
	"cadence_ratio": 1.0,
	"has_open_task": True,
	"inbound_ratio": 0.5,
}


def scored(**overrides):
	return score_deal({**HEALTHY, **overrides})


class ScoreDealTest(UnitTestCase):
	def test_a_healthy_deal_scores_high(self):
		out = scored()
		self.assertGreaterEqual(out["score"], 90)

	def test_factors_account_exactly_for_the_distance_from_100(self):
		out = scored(idle_days=12, has_open_task=False, days_to_close=-3)
		self.assertEqual(out["score"], 100 - sum(f["weight"] for f in out["factors"]))

	def test_more_idle_days_never_raise_the_score(self):
		scores = [scored(idle_days=d)["score"] for d in (0, 5, 10, 20, 40)]
		self.assertEqual(scores, sorted(scores, reverse=True))

	def test_a_past_due_close_date_costs_more_the_later_it_gets(self):
		on_time = scored(days_to_close=10, stage_probability=90)["score"]
		just_over = scored(days_to_close=-2)["score"]
		long_over = scored(days_to_close=-30)["score"]
		self.assertGreater(on_time, just_over)
		self.assertGreater(just_over, long_over)

	def test_a_missing_next_task_is_a_named_factor(self):
		out = scored(has_open_task=False)
		keys = [f["key"] for f in out["factors"]]
		self.assertIn("no_open_task", keys)

	def test_one_sided_outbound_conversation_is_flagged(self):
		out = scored(inbound_ratio=0.0, idle_days=3)
		keys = [f["key"] for f in out["factors"]]
		self.assertIn("no_inbound", keys)

	def test_unknown_close_date_is_not_punished(self):
		out = scored(days_to_close=None)
		keys = [f["key"] for f in out["factors"]]
		self.assertNotIn("close_overdue", keys)
		self.assertNotIn("slip_risk", keys)

	def test_score_is_clamped_to_zero(self):
		out = scored(idle_days=400, has_open_task=False, days_to_close=-200, inbound_ratio=0.0)
		self.assertEqual(out["score"], 0)
		# even clamped, every factor is still reported
		self.assertGreaterEqual(len(out["factors"]), 3)

	def test_every_factor_carries_a_human_label(self):
		out = scored(idle_days=12, has_open_task=False)
		for factor in out["factors"]:
			self.assertTrue(factor["label"])
			self.assertGreater(factor["weight"], 0)


class ForwardLookingFactorTest(UnitTestCase):
	"""The factors that fire before the damage, not after it."""

	def keys(self, **overrides):
		return [f["key"] for f in scored(**overrides)["factors"]]

	def test_a_near_close_date_from_an_early_stage_is_a_slip_risk(self):
		self.assertIn("slip_risk", self.keys(days_to_close=CLOSE_HORIZON_DAYS - 1, stage_probability=20))

	def test_a_near_close_date_from_a_late_stage_is_not(self):
		self.assertNotIn("slip_risk", self.keys(days_to_close=3, stage_probability=90))

	def test_a_distant_close_date_is_not_a_slip_risk_yet(self):
		self.assertNotIn("slip_risk", self.keys(days_to_close=CLOSE_HORIZON_DAYS + 1))

	def test_slip_risk_needs_a_known_stage_probability(self):
		self.assertNotIn("slip_risk", self.keys(days_to_close=3, stage_probability=None))

	def test_a_stage_taking_far_longer_than_its_median_is_flagged(self):
		keys = self.keys(days_in_stage=30, stage_median_days=10)
		self.assertIn("slow_stage", keys)

	def test_a_stage_running_at_its_usual_pace_is_not(self):
		self.assertNotIn("slow_stage", self.keys(days_in_stage=10, stage_median_days=10))

	def test_the_slow_stage_label_names_the_stage_and_the_baseline(self):
		factor = next(
			f for f in scored(days_in_stage=30, stage_median_days=10)["factors"] if f["key"] == "slow_stage"
		)
		self.assertIn("Qualification", factor["label"])
		self.assertIn("10 days", factor["label"])

	def test_no_stage_history_means_no_velocity_claim(self):
		self.assertNotIn("slow_stage", self.keys(days_in_stage=90, stage_median_days=None))

	def test_a_decaying_contact_cadence_is_flagged(self):
		self.assertIn("cadence_slowing", self.keys(cadence_ratio=3.0))

	def test_a_steady_cadence_is_not(self):
		self.assertNotIn("cadence_slowing", self.keys(cadence_ratio=1.1))

	def test_a_slipping_deal_scores_below_an_identical_safe_one(self):
		safe = scored(days_to_close=CLOSE_HORIZON_DAYS + 30)["score"]
		slipping = scored(days_to_close=2)["score"]
		self.assertLess(slipping, safe)


class GetDealHealthTest(IntegrationTestCase):
	"""Feature extraction against real documents.

	Regression: a status_change_log row can carry a null to_date (seen on real
	site data) — extraction must treat it as unknown, not crash.
	"""

	def make_deal(self, **fields):
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Predict Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org, **fields}).insert()
		self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True, ignore_missing=True)
		return deal

	def test_health_of_a_real_deal_is_scored_without_error(self):
		deal = self.make_deal()
		if deal.status_change_log:
			deal.status_change_log[-1].to_date = None
			deal.save()
		out = get_deal_health(deal.name)
		self.assertIn("score", out)
		self.assertIsInstance(out["factors"], list)

	def test_an_overdue_expected_close_on_an_open_deal_is_reported(self):
		"""The only forward-looking factor used to read closed_date, which is written
		only when a deal is Won -- so it could never fire on a live deal."""
		deal = self.make_deal(expected_closure_date=frappe.utils.add_days(frappe.utils.nowdate(), -10))
		keys = [f["key"] for f in get_deal_health(deal.name)["factors"]]
		self.assertIn("close_overdue", keys)

	def test_a_stage_with_no_history_yields_no_median(self):
		self.assertIsNone(_stage_median_days("a status no deal has ever left"))
