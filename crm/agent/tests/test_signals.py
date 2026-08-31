# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Signal engine tests.

The detection functions are pure -- rows in, suggestion dicts out -- so the
thresholds and boundary behaviour are pinned here without a site. The runner
(dedupe, insert, expire, isolation) is exercised against the test site at the
end, scoped to its own fixtures: this site is shared, so nothing here asserts
a site-wide count.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.agent.config import SIGNAL_DEFAULTS, SignalConfig
from crm.agent.signals import (
	CLOSE_HORIZON_DAYS,
	COOLING_MIN_GAP_DAYS,
	DISMISS_COOLDOWN_DAYS,
	EARLY_STAGE_PROBABILITY,
	EXPIRY_COOLDOWN_DAYS,
	IDLE_DEAL_DAYS,
	MAX_OPEN_PER_USER,
	PLAN_MISSED_SCORE_BASE,
	TITLE_MAX_LENGTH,
	_batched,
	_latest_activity,
	_sla_lead_rows,
	_stale_plan_rows,
	cadence_ratio,
	cap_per_user,
	dedupe,
	find_close_date_at_risk,
	find_cooling_deals,
	find_idle_deals,
	find_missing_next_step,
	find_sla_breached_leads,
	find_stale_plan_items,
	purge_old_suggestions,
	run_signals,
	trim_open_over_cap,
)

NOW = datetime(2026, 8, 14, 12, 0, 0)


class PinnedSignalConfig:
	"""Run the signal job against thresholds this file states, not the site's.

	``run_signals`` returns 0 the moment ``signals_enabled`` is off, so every
	end-to-end assertion below silently depended on a Single that any admin --
	or any earlier test in the run -- can flip. Five of them failed on a dev site
	whose Assistant settings page had been opened once, and passed in CI only
	because CI never saves those settings. What is under test here is the runner;
	reading the config has its own coverage in ``test_config`` and
	``test_settings_endpoint``.

	``max_open_per_user`` is pinned out of the way rather than to its default.
	It is the one threshold measured against rows this suite did not write --
	every open suggestion on the site counts towards it -- so at its real value
	a shared site that has been running the hourly job decides whether the
	runner is allowed to create anything, and these assertions turn into a
	report on the fixture data. The cap has its own suites below, each with its
	own rep and its own ceiling.
	"""

	SIGNAL_CONFIG = SignalConfig(
		signals_enabled=True,
		idle_deal_days=SIGNAL_DEFAULTS["idle_deal_days"],
		suggestion_ttl_days=SIGNAL_DEFAULTS["suggestion_ttl_days"],
		dismiss_cooldown_days=SIGNAL_DEFAULTS["dismiss_cooldown_days"],
		close_horizon_days=SIGNAL_DEFAULTS["close_horizon_days"],
		max_open_per_user=1_000_000,
	)

	def setUp(self):
		super().setUp()
		patcher = mock.patch("crm.agent.signals.get_signal_config", return_value=self.SIGNAL_CONFIG)
		patcher.start()
		self.addCleanup(patcher.stop)


def deal_row(**overrides):
	row = {
		"name": "CRM-DEAL-1",
		"organization": "Acme",
		"deal_owner": "rep@example.com",
		"next_step": None,
		"status": "Qualification",
		"stage_probability": 20.0,
		"expected_closure_date": None,
		"creation": NOW - timedelta(days=30),
	}
	row.update(overrides)
	return row


def lead_row(**overrides):
	row = {
		"name": "CRM-LEAD-1",
		"lead_name": "Jane Doe",
		"lead_owner": "rep@example.com",
		"sla": "Default",
		"sla_status": "First Response Due",
		"response_by": NOW - timedelta(hours=2),
		"first_response_time": None,
	}
	row.update(overrides)
	return row


def plan_row(**overrides):
	row = {
		"activity_type": "Call",
		"planned_date": NOW.date() - timedelta(days=3),
		"note": "Call Acme about pricing",
		"status": "Planned",
		"reference_doctype": "CRM Deal",
		"reference_docname": "CRM-DEAL-1",
		"user": "rep@example.com",
	}
	row.update(overrides)
	return row


class IdleDealTest(UnitTestCase):
	def test_a_deal_idle_past_the_threshold_fires(self):
		activity = {"CRM-DEAL-1": NOW - timedelta(days=IDLE_DEAL_DAYS, hours=3)}
		out = find_idle_deals([deal_row()], activity, NOW)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["signal"], "idle_deal")
		self.assertEqual(out[0]["reference_docname"], "CRM-DEAL-1")
		self.assertEqual(out[0]["user"], "rep@example.com")

	def test_a_deal_active_just_inside_the_threshold_does_not_fire(self):
		activity = {"CRM-DEAL-1": NOW - timedelta(days=IDLE_DEAL_DAYS, hours=-2)}
		self.assertEqual(find_idle_deals([deal_row()], activity, NOW), [])

	def test_a_deal_with_no_activity_at_all_uses_creation(self):
		out = find_idle_deals([deal_row()], {}, NOW)
		self.assertEqual(len(out), 1)

	def test_a_recently_created_deal_with_no_activity_does_not_fire(self):
		rows = [deal_row(creation=NOW - timedelta(days=1))]
		self.assertEqual(find_idle_deals(rows, {}, NOW), [])

	def test_the_threshold_is_the_callers_to_set(self):
		activity = {"CRM-DEAL-1": NOW - timedelta(days=4)}
		self.assertEqual(find_idle_deals([deal_row()], activity, NOW), [])
		self.assertEqual(len(find_idle_deals([deal_row()], activity, NOW, idle_days=3)), 1)

	def test_factors_carry_the_idle_days_with_a_human_label(self):
		activity = {"CRM-DEAL-1": NOW - timedelta(days=10)}
		factor = find_idle_deals([deal_row()], activity, NOW)[0]["factors"][0]
		self.assertEqual(factor["key"], "idle_days")
		self.assertEqual(factor["value"], 10)
		self.assertIn("10 days", factor["label"])

	def test_a_very_long_organization_name_cannot_overflow_the_title(self):
		"""CRM Suggestion.title is Data(140) and so is an organization name, so an
		unclipped label used to raise CharacterLengthExceededError out of the insert."""
		out = find_idle_deals([deal_row(organization="A" * 200)], {}, NOW)
		self.assertLessEqual(len(out[0]["title"]), TITLE_MAX_LENGTH)


class MissingNextStepTest(UnitTestCase):
	def test_no_open_task_and_empty_next_step_fires(self):
		out = find_missing_next_step([deal_row()], open_tasks=set())
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["signal"], "no_next_step")

	def test_an_open_task_suppresses(self):
		out = find_missing_next_step([deal_row()], open_tasks={"CRM-DEAL-1"})
		self.assertEqual(out, [])

	def test_a_filled_next_step_suppresses(self):
		rows = [deal_row(next_step="Send proposal")]
		self.assertEqual(find_missing_next_step(rows, open_tasks=set()), [])


class LeadSlaTest(UnitTestCase):
	def test_response_overdue_fires(self):
		out = find_sla_breached_leads([lead_row()], NOW)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["signal"], "lead_sla")

	def test_a_failed_sla_status_fires_even_without_response_by(self):
		rows = [lead_row(response_by=None, sla_status="Failed")]
		self.assertEqual(len(find_sla_breached_leads(rows, NOW)), 1)

	def test_a_lead_already_responded_to_does_not_fire(self):
		rows = [lead_row(first_response_time=NOW - timedelta(hours=1))]
		self.assertEqual(find_sla_breached_leads(rows, NOW), [])

	def test_a_lead_without_an_sla_does_not_fire(self):
		rows = [lead_row(sla=None, response_by=None)]
		self.assertEqual(find_sla_breached_leads(rows, NOW), [])

	def test_a_lead_still_inside_its_window_does_not_fire(self):
		rows = [lead_row(response_by=NOW + timedelta(hours=1))]
		self.assertEqual(find_sla_breached_leads(rows, NOW), [])


class CloseDateAtRiskTest(UnitTestCase):
	"""The forward-looking detector: it must fire before the date, not after."""

	def row(self, **overrides):
		overrides.setdefault("expected_closure_date", NOW.date() + timedelta(days=5))
		return deal_row(**overrides)

	def test_a_near_close_date_from_an_early_stage_fires_while_still_in_the_future(self):
		out = find_close_date_at_risk([self.row()], set(), NOW)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["signal"], "close_at_risk")
		self.assertEqual(out[0]["factors"][0]["value"], 5)

	def test_a_close_date_beyond_the_horizon_does_not_fire(self):
		row = self.row(expected_closure_date=NOW.date() + timedelta(days=CLOSE_HORIZON_DAYS + 1))
		self.assertEqual(find_close_date_at_risk([row], set(), NOW), [])

	def test_a_late_stage_deal_closing_soon_is_not_at_risk(self):
		row = self.row(stage_probability=EARLY_STAGE_PROBABILITY + 10)
		self.assertEqual(find_close_date_at_risk([row], set(), NOW), [])

	def test_a_scheduled_task_suppresses_it(self):
		self.assertEqual(find_close_date_at_risk([self.row()], {"CRM-DEAL-1"}, NOW), [])

	def test_a_deal_with_no_expected_close_date_is_never_at_risk(self):
		self.assertEqual(find_close_date_at_risk([deal_row()], set(), NOW), [])

	def test_urgency_rises_as_the_date_approaches(self):
		far = find_close_date_at_risk(
			[self.row(expected_closure_date=NOW.date() + timedelta(days=12))], set(), NOW
		)
		near = find_close_date_at_risk(
			[self.row(expected_closure_date=NOW.date() + timedelta(days=1))], set(), NOW
		)
		self.assertGreater(near[0]["score"], far[0]["score"])

	def test_every_factor_carries_a_human_label(self):
		for factor in find_close_date_at_risk([self.row()], set(), NOW)[0]["factors"]:
			self.assertTrue(factor["label"])
			self.assertIn("key", factor)


class CadenceTest(UnitTestCase):
	def history(self, *days_ago):
		return [NOW - timedelta(days=d) for d in days_ago]

	def test_too_few_touches_have_no_cadence(self):
		self.assertIsNone(cadence_ratio(self.history(10, 9), NOW))

	def test_a_steady_cadence_reports_a_ratio_near_one(self):
		ratio, gap, median = cadence_ratio(self.history(9, 6, 3), NOW)
		self.assertAlmostEqual(median, 3.0)
		self.assertAlmostEqual(gap, 3.0)
		self.assertAlmostEqual(ratio, 1.0)

	def test_a_stretching_gap_reports_a_ratio_above_one(self):
		ratio, gap, _median = cadence_ratio(self.history(13, 12, 11, 4), NOW)
		self.assertGreater(ratio, 3)
		self.assertAlmostEqual(gap, 4.0)


class CoolingDealTest(UnitTestCase):
	"""Deceleration against a deal's own rhythm, days before the flat threshold."""

	def history(self, *days_ago):
		return {"CRM-DEAL-1": [NOW - timedelta(days=d) for d in days_ago]}

	def test_a_daily_deal_gone_quiet_for_four_days_fires_before_idle_would(self):
		out = find_cooling_deals([deal_row()], self.history(8, 7, 6, 5, 4), NOW)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["signal"], "deal_cooling")
		# the idle detector is still three days away from saying anything
		self.assertEqual(find_idle_deals([deal_row()], {"CRM-DEAL-1": NOW - timedelta(days=4)}, NOW), [])

	def test_a_deal_that_was_always_slow_is_not_cooling(self):
		out = find_cooling_deals([deal_row()], self.history(60, 40, 20, 4), NOW)
		self.assertEqual(out, [])

	def test_a_deal_touched_today_is_not_cooling(self):
		out = find_cooling_deals([deal_row()], self.history(4, 3, 2, 0), NOW)
		self.assertEqual(out, [])

	def test_a_deal_already_idle_is_left_to_the_idle_detector(self):
		out = find_cooling_deals([deal_row()], self.history(30, 29, 28), NOW)
		self.assertEqual(out, [])

	def test_the_factors_explain_the_comparison(self):
		out = find_cooling_deals([deal_row()], self.history(8, 7, 6, 5, 4), NOW)
		keys = {f["key"] for f in out[0]["factors"]}
		self.assertEqual(keys, {"gap_days", "median_gap_days", "cadence_ratio"})
		for factor in out[0]["factors"]:
			self.assertTrue(factor["label"])

	def test_a_gap_narrower_than_the_floor_never_fires(self):
		history = {"CRM-DEAL-1": [NOW - timedelta(hours=h) for h in (30, 28, 26)]}
		measured = cadence_ratio(history["CRM-DEAL-1"], NOW)
		self.assertLess(measured[1], COOLING_MIN_GAP_DAYS)
		self.assertEqual(find_cooling_deals([deal_row()], history, NOW), [])


class StalePlanTest(UnitTestCase):
	def test_a_planned_item_past_its_date_fires(self):
		out = find_stale_plan_items([plan_row()], NOW)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["signal"], "stale_plan")
		self.assertEqual(out[0]["user"], "rep@example.com")
		self.assertEqual(out[0]["suggested_action"], "schedule_call")

	def test_a_missed_item_fires_whatever_its_date(self):
		rows = [plan_row(status="Missed", planned_date=NOW.date())]
		self.assertEqual(len(find_stale_plan_items(rows, NOW)), 1)

	def test_a_future_planned_item_does_not_fire(self):
		rows = [plan_row(planned_date=NOW.date() + timedelta(days=2))]
		self.assertEqual(find_stale_plan_items(rows, NOW), [])

	def test_a_done_item_does_not_fire(self):
		self.assertEqual(find_stale_plan_items([plan_row(status="Done")], NOW), [])

	def test_an_item_with_nothing_to_act_on_is_skipped(self):
		rows = [plan_row(reference_docname=None)]
		self.assertEqual(find_stale_plan_items(rows, NOW), [])

	def test_the_payload_carries_the_activity_for_the_round_trip(self):
		"""propose_week rebuilds the activity from the payload: without it the
		suggested_action mapping is lossy (Meeting -> create_task -> Task)."""
		out = find_stale_plan_items([plan_row(activity_type="Meeting")], NOW)
		self.assertEqual(out[0]["action_payload"]["activity_type"], "Meeting")

	def test_lateness_never_goes_negative(self):
		"""A Missed item whose planned date is still in the future (the matcher
		can write one at a week boundary) must not subtract from the base score
		or render a nonsense '-2 days past the planned date' factor."""
		rows = [plan_row(status="Missed", planned_date=NOW.date() + timedelta(days=2))]
		out = find_stale_plan_items(rows, NOW)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["score"], PLAN_MISSED_SCORE_BASE)
		late = next(f for f in out[0]["factors"] if f["key"] == "days_late")
		self.assertGreaterEqual(late["value"], 0)


class DedupeTest(UnitTestCase):
	def candidate(self, **overrides):
		row = {
			"signal": "idle_deal",
			"reference_doctype": "CRM Deal",
			"reference_docname": "CRM-DEAL-1",
			"user": "rep@example.com",
		}
		row.update(overrides)
		return row

	def existing(self, status, modified_days_ago):
		# mirrors what _existing_suggestions returns, user included: the block
		# is per rep, so the row has to say whose it is
		return {
			"signal": "idle_deal",
			"reference_docname": "CRM-DEAL-1",
			"user": "rep@example.com",
			"status": status,
			"modified": NOW - timedelta(days=modified_days_ago),
		}

	def test_an_open_suggestion_blocks_reemission(self):
		out = dedupe([self.candidate()], [self.existing("Open", 1)], NOW)
		self.assertEqual(out, [])

	def test_a_dismissal_inside_the_cooldown_blocks(self):
		existing = [self.existing("Dismissed", DISMISS_COOLDOWN_DAYS - 1)]
		self.assertEqual(dedupe([self.candidate()], existing, NOW), [])

	def test_a_dismissal_past_the_cooldown_allows_reemission(self):
		existing = [self.existing("Dismissed", DISMISS_COOLDOWN_DAYS + 1)]
		self.assertEqual(len(dedupe([self.candidate()], existing, NOW)), 1)

	def test_an_acceptance_inside_the_cooldown_blocks(self):
		existing = [self.existing("Accepted", DISMISS_COOLDOWN_DAYS - 1)]
		self.assertEqual(dedupe([self.candidate()], existing, NOW), [])

	def test_a_different_signal_on_the_same_record_is_not_blocked(self):
		existing = [self.existing("Open", 1)]
		other = dict(self.candidate(), signal="no_next_step")
		self.assertEqual(len(dedupe([other], existing, NOW)), 1)

	def test_a_freshly_expired_suggestion_does_not_come_straight_back(self):
		"""The runner expires and re-detects in the same hour; without a cooldown of
		its own an Expired row is re-created on the next run, forever."""
		existing = [self.existing("Expired", 0)]
		self.assertEqual(dedupe([self.candidate()], existing, NOW), [])

	def test_an_expired_suggestion_returns_once_its_shorter_cooldown_passes(self):
		existing = [self.existing("Expired", EXPIRY_COOLDOWN_DAYS + 1)]
		self.assertEqual(len(dedupe([self.candidate()], existing, NOW)), 1)

	def test_repeat_dismissals_stretch_the_cooldown_for_that_rep(self):
		"""Dismissals are feedback, not just an audit trail: a rep who has said no to
		this signal three times waits longer than one who never has."""
		existing = [self.existing("Dismissed", DISMISS_COOLDOWN_DAYS + 1)]
		dismissals = {("rep@example.com", "idle_deal"): 3}
		self.assertEqual(len(dedupe([self.candidate()], existing, NOW)), 1)
		self.assertEqual(dedupe([self.candidate()], existing, NOW, dismissals=dismissals), [])

	def test_another_reps_dismissals_do_not_affect_this_one(self):
		existing = [self.existing("Dismissed", DISMISS_COOLDOWN_DAYS + 1)]
		dismissals = {("someone-else@example.com", "idle_deal"): 5}
		self.assertEqual(len(dedupe([self.candidate()], existing, NOW, dismissals=dismissals)), 1)

	def test_one_reps_open_row_does_not_block_another_reps_candidate(self):
		"""Two reps can both plan the same deal. A's open suggestion used to
		block B's forever, because the key carried no user."""
		existing = [self.existing("Open", 1)]
		other_rep = self.candidate(user="other@example.com")
		self.assertEqual(len(dedupe([other_rep], existing, NOW)), 1)

	def test_two_candidates_for_the_same_key_collapse_to_the_higher_ranked_one(self):
		"""One run can detect the same (signal, record, user) twice — a missed
		Call and a missed Email on one deal are both stale_plan on it — and used
		to insert both."""
		a = self.candidate(score=60.0)
		b = self.candidate(score=57.0)
		out = dedupe([b, a], [], NOW)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["score"], 60.0)

	def test_two_candidates_for_different_users_both_survive(self):
		out = dedupe([self.candidate(), self.candidate(user="other@example.com")], [], NOW)
		self.assertEqual(len(out), 2)


class BatchingTest(UnitTestCase):
	"""The hourly job scans every working deal; an unchunked IN clause is the whole
	site in one statement."""

	def test_a_short_list_is_one_batch(self):
		self.assertEqual(list(_batched(["a", "b"], size=10)), [["a", "b"]])

	def test_a_long_list_is_split_and_loses_nothing(self):
		values = list(range(2500))
		batches = list(_batched(values, size=1000))
		self.assertEqual([len(b) for b in batches], [1000, 1000, 500])
		self.assertEqual([v for batch in batches for v in batch], values)

	def test_an_empty_list_yields_no_query(self):
		self.assertEqual(list(_batched([])), [])


class LatestActivityTest(PinnedSignalConfig, IntegrationTestCase):
	"""The input every idle decision rests on, one source at a time.

	The ``comment_type == "Comment"`` carve-out is load-bearing: assignment and
	share comments are written by automation, so counting them would reset the
	idle clock on deals nobody has touched.
	"""

	def setUp(self):
		super().setUp()
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Activity Test Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": self.org}).insert().name
		old = frappe.utils.add_days(frappe.utils.now_datetime(), -30)
		frappe.db.set_value("CRM Deal", self.deal, "creation", old, update_modified=False)
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.db.delete("CRM Suggestion", {"reference_docname": self.deal})
		frappe.db.delete("Communication", {"reference_doctype": "CRM Deal", "reference_name": self.deal})
		frappe.db.delete("Comment", {"reference_doctype": "CRM Deal", "reference_name": self.deal})
		frappe.db.delete("CRM Task", {"reference_doctype": "CRM Deal", "reference_docname": self.deal})
		frappe.db.delete("CRM Call Log", {"reference_doctype": "CRM Deal", "reference_docname": self.deal})
		frappe.delete_doc("CRM Deal", self.deal, force=True, ignore_missing=True)

	def add_communication(self):
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": "Pricing",
				"content": "What is the price?",
				"sender": "jane@acme.test",
				"reference_doctype": "CRM Deal",
				"reference_name": self.deal,
			}
		).insert(ignore_permissions=True)

	def add_task(self):
		frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Call them back",
				"status": "Todo",
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal,
			}
		).insert(ignore_permissions=True)

	def add_call_log(self):
		frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"id": f"activity-test-{self.deal}",
				"from": "+10000000000",
				"to": "+10000000001",
				"type": "Outgoing",
				"status": "Completed",
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal,
			}
		).insert(ignore_permissions=True)

	def add_comment(self, comment_type="Comment"):
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": comment_type,
				"content": "Spoke to them today",
				"reference_doctype": "CRM Deal",
				"reference_name": self.deal,
			}
		).insert(ignore_permissions=True)

	def assert_counts_as_activity(self, add):
		add()
		latest = _latest_activity([self.deal])
		self.assertIn(self.deal, latest)
		self.assertLess((frappe.utils.now_datetime() - latest[self.deal]).total_seconds(), 300)
		self.assertNotIn("idle_deal", self._signals_from_a_run())

	def _signals_from_a_run(self):
		run_signals()
		return frappe.get_all("CRM Suggestion", filters={"reference_docname": self.deal}, pluck="signal")

	def test_a_communication_counts_as_activity(self):
		self.assert_counts_as_activity(self.add_communication)

	def test_a_task_counts_as_activity(self):
		self.assert_counts_as_activity(self.add_task)

	def test_a_call_log_counts_as_activity(self):
		self.assert_counts_as_activity(self.add_call_log)

	def test_a_human_comment_counts_as_activity(self):
		self.assert_counts_as_activity(self.add_comment)

	def test_an_assignment_comment_does_not_count(self):
		self.add_comment(comment_type="Assigned")
		self.assertEqual(_latest_activity([self.deal]), {})
		self.assertIn("idle_deal", self._signals_from_a_run())


class RunSignalsTest(PinnedSignalConfig, IntegrationTestCase):
	"""The runner against the test site: insert, idempotence, expiry, isolation.

	Every assertion is scoped to this suite's own deal. The site is shared and
	carries other suites' records, so a site-wide count would be a coin toss.
	"""

	def setUp(self):
		super().setUp()
		frappe.db.delete("CRM Suggestion", {"title": ("like", "%Signal Test Org%")})
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Signal Test Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": self.org,
			}
		).insert()
		# make it stale: no activity rows exist and creation is pushed back
		old = frappe.utils.add_days(frappe.utils.now_datetime(), -30)
		frappe.db.set_value("CRM Deal", self.deal.name, "creation", old, update_modified=False)

	def tearDown(self):
		frappe.db.delete("CRM Suggestion", {"reference_docname": self.deal.name})
		frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_missing=True)
		super().tearDown()

	def signals_for_the_fixture(self):
		return frappe.get_all("CRM Suggestion", filters={"reference_docname": self.deal.name}, pluck="signal")

	def test_run_signals_is_idempotent(self):
		run_signals()
		first = self.signals_for_the_fixture()
		self.assertIn("idle_deal", first)
		run_signals()
		self.assertEqual(sorted(first), sorted(self.signals_for_the_fixture()))

	def test_expired_suggestions_are_marked(self):
		run_signals()
		name = frappe.get_all(
			"CRM Suggestion",
			filters={"reference_docname": self.deal.name, "signal": "idle_deal"},
			pluck="name",
		)[0]
		past = frappe.utils.add_days(frappe.utils.now_datetime(), -1)
		frappe.db.set_value("CRM Suggestion", name, "expires_on", past, update_modified=False)
		run_signals()
		self.assertEqual(frappe.db.get_value("CRM Suggestion", name, "status"), "Expired")

	def test_a_suggestion_that_expires_in_this_run_is_not_re_created_by_it(self):
		"""Expiring before reading the existing rows made the job replace what it had
		just expired, every hour, forever."""
		run_signals()
		before = frappe.db.count("CRM Suggestion", {"reference_docname": self.deal.name})
		past = frappe.utils.add_days(frappe.utils.now_datetime(), -1)
		frappe.db.set_value(
			"CRM Suggestion",
			{"reference_docname": self.deal.name},
			"expires_on",
			past,
			update_modified=False,
		)
		run_signals()
		self.assertEqual(frappe.db.count("CRM Suggestion", {"reference_docname": self.deal.name}), before)

	def test_a_close_date_at_risk_is_emitted_end_to_end(self):
		frappe.db.set_value(
			"CRM Deal",
			self.deal.name,
			{"expected_closure_date": frappe.utils.add_days(frappe.utils.nowdate(), 3)},
			update_modified=False,
		)
		run_signals()
		self.assertIn("close_at_risk", self.signals_for_the_fixture())

	def test_the_job_returns_nothing_when_signals_are_switched_off(self):
		off = SignalConfig(
			signals_enabled=False,
			idle_deal_days=7,
			suggestion_ttl_days=14,
			dismiss_cooldown_days=14,
			close_horizon_days=14,
		)
		with mock.patch("crm.agent.signals.get_signal_config", return_value=off):
			self.assertEqual(run_signals(), 0)
		self.assertEqual(self.signals_for_the_fixture(), [])

	def test_one_bad_candidate_does_not_cost_the_whole_run(self):
		"""A title over 140 characters or a deleted owner raises out of the insert.
		Without per-candidate isolation that one record rolled back every suggestion
		the hourly job had already created."""
		good = {
			"signal": "idle_deal",
			"title": "Re-engage the fixture",
			"reference_doctype": "CRM Deal",
			"reference_docname": self.deal.name,
			"user": None,
			"suggested_action": "create_task",
			"action_payload": {"title": "Re-engage"},
			"factors": [{"key": "idle_days", "label": "No activity for 30 days", "value": 30}],
			"rationale": "No activity.",
			"score": 50.0,
		}
		bad = dict(good, signal="no_next_step", user="deleted-user@nowhere.invalid")
		with mock.patch("crm.agent.signals._collect_candidates", return_value=[bad, good]):
			created = run_signals()
		self.assertEqual(created, 1)
		self.assertEqual(self.signals_for_the_fixture(), ["idle_deal"])

	def test_the_run_does_not_commit_during_a_test(self):
		"""A commit inside the job breaks per-test rollback and leaks fixtures onto a
		shared site, so the scheduler's commit is skipped under frappe.flags.in_test."""
		with mock.patch.object(frappe.db, "commit") as commit:
			run_signals()
		commit.assert_not_called()


class PurgeTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Purge Test Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert().name
		self.addCleanup(frappe.delete_doc, "CRM Deal", self.deal, force=True, ignore_missing=True)
		self.addCleanup(frappe.db.delete, "CRM Suggestion", {"reference_docname": self.deal})

	def make(self, status, days_old):
		name = (
			frappe.get_doc(
				{
					"doctype": "CRM Suggestion",
					"signal": "idle_deal",
					"title": "Purge fixture",
					"reference_doctype": "CRM Deal",
					"reference_docname": self.deal,
					"status": status,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.set_value(
			"CRM Suggestion",
			name,
			"modified",
			frappe.utils.add_days(frappe.utils.now_datetime(), -days_old),
			update_modified=False,
		)
		return name

	def test_settled_rows_past_the_window_go_and_the_rest_stay(self):
		stale = self.make("Dismissed", 200)
		recent = self.make("Dismissed", 2)
		still_open = self.make("Open", 200)
		purge_old_suggestions()
		self.assertFalse(frappe.db.exists("CRM Suggestion", stale))
		self.assertTrue(frappe.db.exists("CRM Suggestion", recent))
		self.assertTrue(frappe.db.exists("CRM Suggestion", still_open))

	def test_accepted_rows_past_the_window_go_too(self):
		"""An accepted suggestion has done its job; it is settled like a dismissed
		one and stops being evidence at the same age."""
		old_accepted = self.make("Accepted", 200)
		fresh_accepted = self.make("Accepted", 2)
		purge_old_suggestions()
		self.assertFalse(frappe.db.exists("CRM Suggestion", old_accepted))
		self.assertTrue(frappe.db.exists("CRM Suggestion", fresh_accepted))


SLA_REP = "sla-rep@crmtest.test"


class SlaLeadRowsTest(IntegrationTestCase):
	"""The query that decides which leads the SLA detector even considers.

	The detector itself is pure and well covered, but it only ever sees what
	this query hands it — so an exclusion that silently stops working (a Lost
	lead re-entering the set, an unowned one arriving with nobody to notify)
	fails here rather than as a suggestion nobody can action.
	"""

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", SLA_REP):
			user = frappe.get_doc(
				{"doctype": "User", "email": SLA_REP, "first_name": "SLA Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")

		self.open_status = frappe.get_all(
			"CRM Lead Status", filters={"type": ("in", ("Open", "Ongoing"))}, pluck="name"
		)
		self.dead_status = frappe.get_all("CRM Lead Status", filters={"type": "Lost"}, pluck="name")
		if not self.open_status or not self.dead_status:
			self.skipTest("site has no open and lost lead statuses")

		# A site with no SLA policy would make every assertion here vacuous, so the
		# fixture brings its own rather than skipping.
		self.sla = self.ensure_sla()

	def ensure_sla(self) -> str:
		name = "SLA Rows Test Policy"
		if frappe.db.exists("CRM Service Level Agreement", name):
			return name
		priority = frappe.get_all("CRM Communication Status", limit=1, pluck="name")
		if not priority:
			self.skipTest("site has no communication status to build an SLA priority from")
		doc = frappe.get_doc(
			{
				"doctype": "CRM Service Level Agreement",
				"sla_name": name,
				"apply_on": "CRM Lead",
				"enabled": 1,
				"priorities": [
					{
						"priority": priority[0],
						"default_priority": 1,
						"first_response_time": 3600,
					}
				],
				"working_hours": [
					{"workday": day, "start_time": "09:00:00", "end_time": "17:00:00"}
					for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
				],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Service Level Agreement", doc.name, force=True)
		return doc.name

	def make_lead(self, **overrides) -> str:
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "SLA",
				"last_name": "Candidate",
				"lead_owner": SLA_REP,
				"status": self.open_status[0],
				"sla": self.sla,
				**overrides,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Lead", lead.name, force=True)
		return lead.name

	def names(self) -> set[str]:
		return {row["name"] for row in _sla_lead_rows()}

	def test_an_open_owned_lead_with_an_sla_is_considered(self):
		name = self.make_lead()
		self.assertIn(name, self.names())

	def test_a_dead_lead_is_not_chased(self):
		name = self.make_lead()
		frappe.db.set_value("CRM Lead", name, "status", self.dead_status[0])
		self.assertNotIn(name, self.names())

	def test_an_unowned_lead_is_not_chased(self):
		"""Nobody to notify means nothing to suggest — an unowned breach is a
		manager's report, not a rep's inbox item."""
		name = self.make_lead()
		frappe.db.set_value("CRM Lead", name, "lead_owner", "")
		self.assertNotIn(name, self.names())

	def test_a_converted_lead_is_not_chased(self):
		name = self.make_lead()
		frappe.db.set_value("CRM Lead", name, "converted", 1)
		self.assertNotIn(name, self.names())


class CapPerUserTest(UnitTestCase):
	"""The ranking that keeps an inbox a worklist.

	``no_next_step`` fires on every open deal with no task, so on an imported
	pipeline the candidate list is the pipeline. The cap is what stops that
	reaching the database, and the ordering is what stops the surviving rows
	changing every hour.
	"""

	def candidates(self, n, user="rep@example.com", score=40.0, signal="no_next_step"):
		return [
			{
				"signal": signal,
				"reference_doctype": "CRM Deal",
				"reference_docname": f"CRM-DEAL-{i:03d}",
				"user": user,
				"score": score,
			}
			for i in range(n)
		]

	def test_a_short_list_is_untouched(self):
		rows = self.candidates(3)
		self.assertEqual(len(cap_per_user(rows, {}, 30)), 3)

	def test_the_cap_is_the_ceiling(self):
		self.assertEqual(len(cap_per_user(self.candidates(500), {}, 30)), 30)

	def test_what_a_rep_already_holds_counts_against_the_cap(self):
		out = cap_per_user(self.candidates(500), {"rep@example.com": 28}, 30)
		self.assertEqual(len(out), 2)

	def test_a_full_inbox_gets_nothing_new(self):
		self.assertEqual(cap_per_user(self.candidates(500), {"rep@example.com": 30}, 30), [])

	def test_an_overflowing_inbox_does_not_go_negative(self):
		self.assertEqual(cap_per_user(self.candidates(5), {"rep@example.com": 900}, 30), [])

	def test_each_rep_gets_their_own_ceiling(self):
		rows = self.candidates(50, user="a@example.com") + self.candidates(50, user="b@example.com")
		out = cap_per_user(rows, {"a@example.com": 4}, 5)
		self.assertEqual(sum(1 for r in out if r["user"] == "a@example.com"), 1)
		self.assertEqual(sum(1 for r in out if r["user"] == "b@example.com"), 5)

	def test_unowned_candidates_share_one_bucket(self):
		rows = self.candidates(10, user=None) + self.candidates(10, user="")
		self.assertEqual(len(cap_per_user(rows, {}, 5)), 5)

	def test_the_highest_scoring_candidates_survive(self):
		rows = [
			{"signal": "idle_deal", "reference_docname": "D1", "user": "r", "score": 10.0},
			{"signal": "sla_breach", "reference_docname": "D2", "user": "r", "score": 80.0},
			{"signal": "no_next_step", "reference_docname": "D3", "user": "r", "score": 40.0},
		]
		self.assertEqual([r["reference_docname"] for r in cap_per_user(rows, {}, 2)], ["D2", "D3"])

	def test_equal_scores_are_broken_the_same_way_every_run(self):
		"""``no_next_step`` gives every candidate 40, so score alone is not an order.

		Without a tie-break the surviving rows would be whichever the deal query
		returned first, and a rep working their inbox would watch it reshuffle
		on the hour.
		"""
		rows = self.candidates(20)
		first = cap_per_user(rows, {}, 5)
		shuffled = list(reversed(rows))
		self.assertEqual(first, cap_per_user(shuffled, {}, 5))

	def test_a_missing_score_is_not_a_crash(self):
		rows = [{"signal": "idle_deal", "reference_docname": "D1", "user": "r"}]
		self.assertEqual(len(cap_per_user(rows, {}, 5)), 1)


CAP_REP = "cap-rep@crmtest.test"


class TrimOverCapTest(IntegrationTestCase):
	"""Bringing a queue that is already over the ceiling back under it.

	``cap_per_user`` only governs rows about to be written. A site that ran
	before the cap existed -- which is every site that has run at all -- keeps
	its backlog until something expires it, and that is this.
	"""

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", CAP_REP):
			frappe.get_doc(
				{"doctype": "User", "email": CAP_REP, "first_name": "Cap Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True).add_roles("Sales User")
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Cap Test Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert().name
		self.addCleanup(frappe.delete_doc, "CRM Deal", self.deal, force=True, ignore_missing=True)
		self.addCleanup(frappe.db.delete, "CRM Suggestion", {"user": CAP_REP})

	def make(self, score, status="Open"):
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Suggestion",
					"signal": "no_next_step",
					"title": f"Cap fixture {score}",
					"reference_doctype": "CRM Deal",
					"reference_docname": self.deal,
					"user": CAP_REP,
					"status": status,
					"score": score,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def open_names(self):
		return set(
			frappe.get_all("CRM Suggestion", filters={"user": CAP_REP, "status": "Open"}, pluck="name")
		)

	def test_a_queue_under_the_cap_is_left_alone(self):
		kept = {self.make(10), self.make(20)}
		trim_open_over_cap(frappe.utils.now_datetime(), 5)
		self.assertEqual(self.open_names(), kept)

	def test_the_lowest_scoring_rows_are_the_ones_expired(self):
		low, mid, high = self.make(10), self.make(50), self.make(90)
		trim_open_over_cap(frappe.utils.now_datetime(), 2)
		self.assertEqual(self.open_names(), {mid, high})
		self.assertEqual(frappe.db.get_value("CRM Suggestion", low, "status"), "Expired")

	def test_trimming_twice_expires_nothing_the_second_time(self):
		for score in (10, 20, 30, 40):
			self.make(score)
		now = frappe.utils.now_datetime()
		self.assertEqual(trim_open_over_cap(now, 2), 2)
		survivors = self.open_names()
		self.assertEqual(trim_open_over_cap(now, 2), 0)
		self.assertEqual(self.open_names(), survivors)

	def test_the_survivors_do_not_change_between_runs(self):
		"""Every ``no_next_step`` row carries the same score, so the tie-break
		is the whole ordering. If it were unstable the trim would expire a
		different pair each hour and the inbox would churn."""
		for _ in range(6):
			self.make(40)
		now = frappe.utils.now_datetime()
		trim_open_over_cap(now, 3)
		first = self.open_names()
		# reopening them all puts the queue back over the cap with the same rows
		frappe.db.set_value("CRM Suggestion", {"user": CAP_REP}, "status", "Open", update_modified=False)
		trim_open_over_cap(now, 3)
		self.assertEqual(self.open_names(), first)

	def test_an_expired_row_does_not_count_towards_the_cap(self):
		self.make(10, status="Expired")
		self.make(20, status="Expired")
		kept = {self.make(30)}
		trim_open_over_cap(frappe.utils.now_datetime(), 1)
		self.assertEqual(self.open_names(), kept)

	def test_the_default_cap_is_the_one_an_admin_sees(self):
		self.assertEqual(MAX_OPEN_PER_USER, SIGNAL_DEFAULTS["max_open_per_user"])


class RunSignalsRespectsTheCapTest(PinnedSignalConfig, IntegrationTestCase):
	"""End to end: three eligible deals, a ceiling of one, one row written.

	The pure test proves the ranking and the trim test proves the cleanup; this
	is the wiring between them -- that ``run_signals`` reads the cap from the
	config at all, and reads each rep's remaining room after expiring rather
	than before.
	"""

	SIGNAL_CONFIG = SignalConfig(
		signals_enabled=True,
		idle_deal_days=SIGNAL_DEFAULTS["idle_deal_days"],
		suggestion_ttl_days=SIGNAL_DEFAULTS["suggestion_ttl_days"],
		dismiss_cooldown_days=SIGNAL_DEFAULTS["dismiss_cooldown_days"],
		close_horizon_days=SIGNAL_DEFAULTS["close_horizon_days"],
		max_open_per_user=1,
	)

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", CAP_REP):
			frappe.get_doc(
				{"doctype": "User", "email": CAP_REP, "first_name": "Cap Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True).add_roles("Sales User")
		frappe.db.delete("CRM Suggestion", {"user": CAP_REP})
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Cap Run Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		# fresh deals: old enough for no_next_step, too new for idle_deal, so the
		# candidate count is exactly the number of deals
		self.deals = [
			frappe.get_doc({"doctype": "CRM Deal", "organization": org, "deal_owner": CAP_REP}).insert().name
			for _ in range(3)
		]
		for name in self.deals:
			self.addCleanup(frappe.delete_doc, "CRM Deal", name, force=True, ignore_missing=True)
		self.addCleanup(frappe.db.delete, "CRM Suggestion", {"user": CAP_REP})

	def open_for_rep(self):
		return frappe.get_all("CRM Suggestion", filters={"user": CAP_REP, "status": "Open"}, pluck="signal")

	def test_three_eligible_deals_produce_one_suggestion(self):
		run_signals()
		self.assertEqual(self.open_for_rep(), ["no_next_step"])

	def test_a_second_run_does_not_top_the_inbox_back_up(self):
		run_signals()
		run_signals()
		self.assertEqual(len(self.open_for_rep()), 1)


class StalePlanRowsTest(IntegrationTestCase):
	"""The query side of the stale-plan signal must leave hand-corrected items
	alone — the same respect the matcher shows (``_match_plan`` filters
	``manual_override``). ``mark_missed`` sets it, so without this filter a rep
	who wrote an item off was nagged to do it within the hour."""

	def test_a_hand_corrected_item_is_not_a_candidate(self):
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Stale Plan Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		deals = []
		for _ in range(2):
			deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert(
				ignore_permissions=True
			)
			self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True, ignore_missing=True)
			deals.append(deal.name)

		now = frappe.utils.now_datetime()
		monday = now.date() - timedelta(days=now.weekday() + 7)
		plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": "Administrator",
				"week_start": monday,
				"items": [
					{
						"activity_type": "Call",
						"planned_date": monday,
						"status": "Missed",
						"manual_override": 0,
						"reference_doctype": "CRM Deal",
						"reference_docname": deals[0],
					},
					{
						"activity_type": "Call",
						"planned_date": monday,
						"status": "Missed",
						"manual_override": 1,
						"reference_doctype": "CRM Deal",
						"reference_docname": deals[1],
					},
				],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Rep Plan", plan.name, force=True, ignore_missing=True)

		names = {row["reference_docname"] for row in _stale_plan_rows(now)}
		self.assertIn(deals[0], names)
		self.assertNotIn(deals[1], names)
