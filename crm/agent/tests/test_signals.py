# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Signal engine tests.

The detection functions are pure -- rows in, suggestion dicts out -- so the
thresholds and boundary behaviour are pinned here without a site. The runner
(dedupe, insert, expire) is exercised against the test site at the end.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.agent.signals import (
	DISMISS_COOLDOWN_DAYS,
	IDLE_DEAL_DAYS,
	dedupe,
	find_idle_deals,
	find_missing_next_step,
	find_sla_breached_leads,
	run_signals,
)

NOW = datetime(2026, 8, 14, 12, 0, 0)


def deal_row(**overrides):
	row = {
		"name": "CRM-DEAL-1",
		"organization": "Acme",
		"deal_owner": "rep@example.com",
		"next_step": None,
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

	def test_factors_carry_the_idle_days_for_explainability(self):
		activity = {"CRM-DEAL-1": NOW - timedelta(days=10)}
		out = find_idle_deals([deal_row()], activity, NOW)
		self.assertEqual(out[0]["factors"]["idle_days"], 10)


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


class DedupeTest(UnitTestCase):
	def candidate(self):
		return {
			"signal": "idle_deal",
			"reference_doctype": "CRM Deal",
			"reference_docname": "CRM-DEAL-1",
		}

	def existing(self, status, modified_days_ago):
		return {
			"signal": "idle_deal",
			"reference_docname": "CRM-DEAL-1",
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

	def test_a_different_signal_on_the_same_record_is_not_blocked(self):
		existing = [self.existing("Open", 1)]
		other = dict(self.candidate(), signal="no_next_step")
		self.assertEqual(len(dedupe([other], existing, NOW)), 1)


class RunSignalsTest(IntegrationTestCase):
	"""The runner against the test site: insert, idempotence, expiry."""

	def setUp(self):
		super().setUp()
		frappe.db.delete("CRM Suggestion")
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
		frappe.db.delete("CRM Suggestion")
		frappe.delete_doc("CRM Deal", self.deal.name, force=True)
		super().tearDown()

	def test_run_signals_is_idempotent(self):
		run_signals()
		first = frappe.get_all(
			"CRM Suggestion", filters={"reference_docname": self.deal.name}, pluck="signal"
		)
		self.assertIn("idle_deal", first)
		run_signals()
		second = frappe.get_all(
			"CRM Suggestion", filters={"reference_docname": self.deal.name}, pluck="signal"
		)
		self.assertEqual(sorted(first), sorted(second))

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
