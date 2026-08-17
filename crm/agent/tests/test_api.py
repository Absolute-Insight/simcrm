# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Endpoint tests. The client is stubbed; the flag and degrade paths are the subject."""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent import api as api_mod
from crm.agent.config import AgentConfig
from crm.agent.errors import AgentUnavailable
from crm.agent.schemas import ThreadSummary

DISABLED = AgentConfig(enabled=False, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)
ENABLED = AgentConfig(enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)
SUMMARY = ThreadSummary(summary="Stalled on pricing.", next_steps=["Send quote"], sentiment="neutral")


# Both endpoints run their config through the budget counter; the tests that are not
# about the budget stub it out rather than depending on a shared redis counter.
def no_budget_check():
	return mock.patch.object(api_mod, "_budget_spent", return_value=False)


class FlagTest(IntegrationTestCase):
	def test_disabled_returns_a_status_and_never_calls_the_model(self):
		with mock.patch.object(api_mod, "get_config", return_value=DISABLED):
			with mock.patch.object(api_mod.client, "complete") as complete:
				result = api_mod.summarise_thread("CRM Deal", "CRM-DEAL-0001")

		self.assertEqual(result, {"status": "disabled"})
		complete.assert_not_called()


class DegradeTest(IntegrationTestCase):
	def test_unavailable_model_degrades_instead_of_raising(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.tools, "read_record", return_value={"name": "CRM-DEAL-0001"}),
			mock.patch.object(api_mod.tools, "read_thread", return_value=[]),
			mock.patch.object(api_mod.client, "complete", side_effect=AgentUnavailable("down")),
			no_budget_check(),
		):
			result = api_mod.summarise_thread("CRM Deal", "CRM-DEAL-0001")

		self.assertEqual(result["status"], "unavailable")


class HappyPathTest(IntegrationTestCase):
	def test_returns_the_validated_summary_as_a_plain_dict(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.tools, "read_record", return_value={"name": "CRM-DEAL-0001"}),
			mock.patch.object(api_mod.tools, "read_thread", return_value=[]),
			mock.patch.object(api_mod.client, "complete", return_value=SUMMARY) as complete,
			no_budget_check(),
		):
			result = api_mod.summarise_thread("CRM Deal", "CRM-DEAL-0001")

		self.assertEqual(result["status"], "ok")
		self.assertEqual(result["summary"]["sentiment"], "neutral")
		self.assertEqual(result["summary"]["next_steps"], ["Send quote"])
		self.assertIs(complete.call_args[0][1], ThreadSummary)

	def test_endpoint_is_whitelisted(self):
		"""``frappe.whitelist()`` registers the function object in ``frappe.whitelisted`` --
		it does not set an attribute on it, so membership is what to assert."""
		self.assertIn(api_mod.summarise_thread, frappe.whitelisted)


class RateLimitTest(IntegrationTestCase):
	def test_the_endpoint_is_rate_limited(self):
		"""One call can hold a worker for ``timeout`` x ``MAX_ATTEMPTS`` -- 60s at the
		shipped defaults -- so the cap is what stands between one authenticated user and
		the worker pool. Mirrors ``domain_enrichment``'s check: ``rate_limit`` wraps with
		``functools.wraps``, so ``__wrapped__`` is the evidence the decorator is on."""
		self.assertTrue(hasattr(api_mod.summarise_thread, "__wrapped__"))
		self.assertIsNot(api_mod.summarise_thread, api_mod.summarise_thread.__wrapped__)
		self.assertGreater(api_mod.SUMMARISE_RATE_LIMIT, 0)


class DailyBudgetTest(IntegrationTestCase):
	"""The per-user rate limit bounds a burst; it does not bound a day.

	Fifty users at ten calls a minute is still an unbounded bill against whoever
	hosts the endpoint, so both entry points check a site-wide daily counter.
	"""

	def test_an_exhausted_budget_degrades_and_never_calls_the_model(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod, "_budget_spent", return_value=True),
			mock.patch.object(api_mod.client, "complete") as complete,
			mock.patch.object(api_mod.actions, "propose_reply") as propose,
		):
			summary = api_mod.summarise_thread("CRM Deal", "CRM-DEAL-0001")
			draft = api_mod.draft_reply("CRM Deal", "CRM-DEAL-0001")

		self.assertEqual(summary, {"status": "unavailable"})
		self.assertEqual(draft, {"status": "unavailable"})
		complete.assert_not_called()
		propose.assert_not_called()

	def test_a_budget_of_zero_means_uncapped_rather_than_blocked(self):
		"""Blocking on zero would take the feature down on every site that never set
		the field, which is the opposite of what an unset number should mean."""
		uncapped = AgentConfig(
			enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64, daily_call_budget=0
		)
		self.assertFalse(api_mod._budget_spent(uncapped))

	def test_the_counter_is_scoped_to_the_site(self):
		"""incr is a raw redis command and skips frappe's site prefix, so without the
		site in the key every site on the bench would share one budget."""
		self.assertIn(frappe.local.site, api_mod.budget_key())

	def test_a_dead_cache_does_not_take_the_feature_down(self):
		with mock.patch.object(frappe, "cache", side_effect=RuntimeError("no redis")):
			self.assertFalse(api_mod._budget_spent(ENABLED))

	def test_the_counter_blocks_once_the_budget_is_spent(self):
		tiny = AgentConfig(
			enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64, daily_call_budget=2
		)
		key = api_mod.budget_key()
		frappe.cache().delete(key)
		self.addCleanup(frappe.cache().delete, key)
		self.assertFalse(api_mod._budget_spent(tiny))
		self.assertFalse(api_mod._budget_spent(tiny))
		self.assertTrue(api_mod._budget_spent(tiny))


class TestConnectionTest(IntegrationTestCase):
	"""Until this endpoint existed, the only way to discover a wrong ``base_url``
	was a rep clicking a feature and getting a degraded dialog -- the failure
	reached a user before the admin who caused it."""

	def test_a_working_endpoint_reports_the_model_and_how_long_it_took(self):
		from crm.agent.schemas import ConnectionProbe

		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete", return_value=ConnectionProbe(ok=True)),
		):
			result = api_mod.test_connection()

		self.assertTrue(result["ok"])
		self.assertEqual(result["kind"], "ok")
		self.assertEqual(result["model"], ENABLED.model)
		# The number matters as much as the verdict: it is what the timeout has
		# to clear, and a cold model can take ten times a warm one.
		self.assertIn("latency_ms", result)

	def test_an_unreachable_endpoint_is_reported_not_raised(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(
				api_mod.client, "complete", side_effect=AgentUnavailable("http://x/v1: refused")
			),
		):
			result = api_mod.test_connection()

		self.assertFalse(result["ok"])
		self.assertEqual(result["kind"], "unreachable")
		self.assertIn("refused", result["message"])

	def test_a_model_that_will_not_follow_the_schema_is_a_distinct_failure(self):
		"""Reaching the host proves nothing about guided decoding, and the two
		problems have different fixes -- one is the URL, the other the model."""
		from crm.agent.errors import SchemaMismatch

		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete", side_effect=SchemaMismatch("not JSON")),
		):
			result = api_mod.test_connection()

		self.assertFalse(result["ok"])
		self.assertEqual(result["kind"], "schema")

	def test_it_runs_with_the_tier_switched_off(self):
		"""An endpoint has to be provable *before* it is turned on for reps."""
		from crm.agent.schemas import ConnectionProbe

		with (
			mock.patch.object(api_mod, "get_config", return_value=DISABLED),
			mock.patch.object(api_mod.client, "complete", return_value=ConnectionProbe(ok=True)) as complete,
		):
			result = api_mod.test_connection()

		self.assertTrue(result["ok"])
		complete.assert_called_once()

	def test_the_api_key_never_appears_in_the_result(self):
		keyed = AgentConfig(
			enabled=True,
			base_url="http://x/v1",
			model="m",
			timeout=5,
			max_tokens=64,
			api_key="sk-do-not-leak",
		)
		with (
			mock.patch.object(api_mod, "get_config", return_value=keyed),
			mock.patch.object(api_mod.client, "complete", side_effect=AgentUnavailable("http://x/v1: boom")),
		):
			result = api_mod.test_connection()

		self.assertNotIn("sk-do-not-leak", str(result))

	def test_a_non_admin_cannot_probe_the_endpoint(self):
		"""It makes the server issue an outbound request carrying the API key."""
		email = "agent-probe-nonadmin@crmtest.test"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Probe", "send_welcome_email": 0}
			).insert(ignore_permissions=True).add_roles("Sales User")

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(email)
		with self.assertRaises(frappe.PermissionError):
			api_mod.test_connection()
