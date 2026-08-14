# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deal-health scoring tests — pure feature dicts in, scored verdicts out.

The score is a transparent heuristic: every deduction is attributed to a named
factor, and the factors always account exactly for the distance from 100. The
suite pins monotonicity (worse inputs never raise the score) and the
attribution invariant rather than blessing specific magic numbers.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.agent.predict import get_deal_health, score_deal

HEALTHY = {
	"idle_days": 1,
	"days_in_stage": 5,
	"days_to_close": 30,
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
		on_time = scored(days_to_close=10)["score"]
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


class GetDealHealthTest(IntegrationTestCase):
	"""Feature extraction against real documents.

	Regression: a status_change_log row can carry a null to_date (seen on real
	site data) — extraction must treat it as unknown, not crash.
	"""

	def test_health_of_a_real_deal_is_scored_without_error(self):
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Predict Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert()
		if deal.status_change_log:
			deal.status_change_log[-1].to_date = None
			deal.save()
		out = get_deal_health(deal.name)
		self.assertIn("score", out)
		self.assertIsInstance(out["factors"], list)
