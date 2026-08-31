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


# Every endpoint runs through the per-user minute window and the daily budgets; the
# tests that are not about either stub the whole throttle out rather than depending
# on a shared redis counter.
def no_budget_check():
	return mock.patch.object(api_mod, "_throttled", return_value=False)


def clear_user_window(scope: str, user: str | None = None) -> None:
	from crm.utils import user_rate_key

	frappe.cache().delete(user_rate_key(scope, user=user))


def make_sales_user(email: str, first_name: str) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first_name, "send_welcome_email": 0}
		).insert(ignore_permissions=True).add_roles("Sales User")
	return email


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

	def test_the_same_user_trips_the_per_user_window_and_another_user_does_not(self):
		"""frappe's ``@rate_limit`` keys on the request IP, so on its own it never
		bounded one account: a user behind a rotating address had no limit, and an
		office behind one NAT shared a single bucket. This layer keys on the user."""
		from crm.utils import user_rate_limited

		scope = "crm_agent_rate_test"
		alice = make_sales_user("agent-rate-alice@crmtest.test", "Alice")
		bob = make_sales_user("agent-rate-bob@crmtest.test", "Bob")
		self.addCleanup(frappe.set_user, "Administrator")
		for user in (alice, bob):
			clear_user_window(scope, user)
			self.addCleanup(clear_user_window, scope, user)

		frappe.set_user(alice)
		verdicts = [user_rate_limited(scope, 10) for _ in range(11)]
		self.assertEqual(verdicts[:10], [False] * 10)
		self.assertTrue(verdicts[10])

		frappe.set_user(bob)
		self.assertFalse(user_rate_limited(scope, 10))

	def test_a_user_past_the_window_gets_unavailable_and_the_model_is_never_called(self):
		alice = make_sales_user("agent-rate-alice@crmtest.test", "Alice")
		self.addCleanup(frappe.set_user, "Administrator")
		clear_user_window(api_mod.USER_RATE_SCOPE, alice)
		self.addCleanup(clear_user_window, api_mod.USER_RATE_SCOPE, alice)
		frappe.set_user(alice)
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod, "_budget_spent", return_value=False),
			mock.patch.object(api_mod.tools, "read_record", return_value={}),
			mock.patch.object(api_mod.tools, "read_thread", return_value=[]),
			mock.patch.object(api_mod.client, "complete", return_value=SUMMARY) as complete,
		):
			results = [
				api_mod.summarise_thread("CRM Deal", "CRM-DEAL-0001")
				for _ in range(api_mod.SUMMARISE_RATE_LIMIT + 1)
			]
		self.assertEqual(results[-1], {"status": "unavailable"})
		self.assertEqual(complete.call_count, api_mod.SUMMARISE_RATE_LIMIT)

	def test_a_dead_cache_fails_open(self):
		from crm.utils import user_rate_limited

		with mock.patch.object(frappe, "cache", side_effect=RuntimeError("no redis")):
			self.assertFalse(user_rate_limited("crm_agent_rate_test", 1))


class RoleGateTest(IntegrationTestCase):
	def test_a_user_without_a_sales_role_cannot_call_the_model_endpoints(self):
		"""Each call costs a model call against the configured endpoint; a Website
		User with a session is not a rep and gets nothing."""
		email = "agent-nobody@crmtest.test"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Nobody", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(email)
		with mock.patch.object(api_mod.client, "complete") as complete:
			for call in (
				lambda: api_mod.summarise_thread("CRM Deal", "CRM-DEAL-0001"),
				lambda: api_mod.draft_reply("CRM Deal", "CRM-DEAL-0001"),
				lambda: api_mod.ask_assistant("hello"),
			):
				with self.assertRaises(frappe.PermissionError):
					call()
		complete.assert_not_called()


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
		for key in (api_mod.budget_key(), api_mod.user_budget_key()):
			frappe.cache().delete(key)
			self.addCleanup(frappe.cache().delete, key)
		self.assertFalse(api_mod._budget_spent(tiny))
		self.assertFalse(api_mod._budget_spent(tiny))
		self.assertTrue(api_mod._budget_spent(tiny))

	def test_one_user_cannot_spend_the_whole_site_budget(self):
		"""The per-user share is a fifth of the site's day with a floor of ten, so a
		budget of 100 lets one account make 20 calls and then blocks it while the
		site counter still has room for everyone else."""
		shared = AgentConfig(
			enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64, daily_call_budget=100
		)
		self.assertEqual(api_mod.user_daily_call_budget(shared), 20)
		small = AgentConfig(
			enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64, daily_call_budget=12
		)
		self.assertEqual(api_mod.user_daily_call_budget(small), api_mod.USER_DAILY_BUDGET_FLOOR)

		for key in (api_mod.budget_key(), api_mod.user_budget_key()):
			frappe.cache().delete(key)
			self.addCleanup(frappe.cache().delete, key)
		verdicts = [api_mod._budget_spent(shared) for _ in range(21)]
		self.assertEqual(verdicts[:20], [False] * 20)
		self.assertTrue(verdicts[20])
		self.assertLess(int(frappe.cache().get(api_mod.budget_key()) or 0), shared.daily_call_budget)


class TestConnectionTest(IntegrationTestCase):
	"""Until this endpoint existed, the only way to discover a wrong ``base_url``
	was a rep clicking a feature and getting a degraded dialog -- the failure
	reached a user before the admin who caused it."""

	def setUp(self):
		super().setUp()
		clear_user_window(api_mod.TEST_CONNECTION_RATE_SCOPE)
		self.addCleanup(clear_user_window, api_mod.TEST_CONNECTION_RATE_SCOPE)

	def test_a_rejected_key_is_a_distinct_failure_that_names_the_fix(self):
		"""A 401 is not "unreachable": the host answered, and what is wrong is the
		api_key field. The message has to say so or the admin chases the URL."""
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(
				api_mod.client,
				"complete",
				side_effect=api_mod.client.EndpointRejectedKey(
					"http://x/v1: endpoint rejected the API key (HTTP 401)"
				),
			),
		):
			result = api_mod.test_connection()

		self.assertFalse(result["ok"])
		self.assertEqual(result["kind"], "unauthorised")
		self.assertIn("rejected the API key", result["message"])

	def test_too_many_probes_in_a_minute_are_refused_without_a_model_call(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod, "user_rate_limited", return_value=True),
			mock.patch.object(api_mod.client, "complete") as complete,
		):
			result = api_mod.test_connection()
		self.assertFalse(result["ok"])
		self.assertEqual(result["kind"], "rate_limited")
		complete.assert_not_called()

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


class BudgetRefundTest(IntegrationTestCase):
	"""A refused call must cost nobody anything.

	The site counter used to be charged before the per-user check with no refund
	on refusal, so one capped account's retries — still permitted by the burst
	limiter — could spend the whole site's day on calls that never reached the
	model.
	"""

	def test_a_capped_users_retries_do_not_burn_the_site_budget(self):
		shared = AgentConfig(
			enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64, daily_call_budget=100
		)
		site_key, user_key = api_mod.budget_key(), api_mod.user_budget_key()
		for key in (site_key, user_key):
			frappe.cache().delete(key)
			self.addCleanup(frappe.cache().delete, key)
		# the rep has already spent their share of 20
		frappe.cache().setex(user_key, 3600, api_mod.user_daily_call_budget(shared))

		for _ in range(5):
			self.assertTrue(api_mod._budget_spent(shared))

		# the refusals crept nothing: user counter pinned at its cap, site untouched
		self.assertEqual(int(frappe.cache().get(user_key)), api_mod.user_daily_call_budget(shared))
		self.assertEqual(int(frappe.cache().get(site_key) or 0), 0)

	def test_a_refused_site_budget_charges_neither_counter(self):
		tiny = AgentConfig(
			enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64, daily_call_budget=1
		)
		site_key, user_key = api_mod.budget_key(), api_mod.user_budget_key()
		for key in (site_key, user_key):
			frappe.cache().delete(key)
			self.addCleanup(frappe.cache().delete, key)
		frappe.cache().setex(site_key, 3600, 1)  # the site's day is spent by someone else

		self.assertTrue(api_mod._budget_spent(tiny))
		self.assertEqual(int(frappe.cache().get(site_key)), 1)
		self.assertEqual(int(frappe.cache().get(user_key) or 0), 0)


class InflightSlotTest(IntegrationTestCase):
	"""Bounds simultaneous model calls: each one holds a web worker for up to
	timeout x MAX_ATTEMPTS, so a burst inside the rate limits could still occupy
	the whole gunicorn pool."""

	def _clear(self):
		key = api_mod._inflight_key()
		frappe.cache().delete(key)
		self.addCleanup(frappe.cache().delete, key)
		return key

	def test_a_free_slot_is_taken_and_released(self):
		key = self._clear()
		with api_mod._model_call_slot() as free:
			self.assertTrue(free)
			self.assertEqual(int(frappe.cache().get(key)), 1)
		self.assertEqual(int(frappe.cache().get(key) or 0), 0)

	def test_a_full_slot_set_reports_busy_and_releases_its_probe(self):
		key = self._clear()
		frappe.cache().setex(key, 60, api_mod.MAX_CONCURRENT_MODEL_CALLS)
		with api_mod._model_call_slot() as free:
			self.assertFalse(free)
		self.assertEqual(int(frappe.cache().get(key)), api_mod.MAX_CONCURRENT_MODEL_CALLS)

	def test_a_dead_cache_fails_open(self):
		with mock.patch.object(frappe, "cache", side_effect=RuntimeError("no redis")):
			with api_mod._model_call_slot() as free:
				self.assertTrue(free)

	def test_the_endpoint_reports_unavailable_when_every_slot_is_taken(self):
		key = self._clear()
		frappe.cache().setex(key, 60, api_mod.MAX_CONCURRENT_MODEL_CALLS)
		with (
			no_budget_check(),
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.tools, "read_record", return_value={"name": "X"}),
			mock.patch.object(api_mod.tools, "read_thread", return_value=[]),
			mock.patch.object(api_mod.client, "complete") as complete,
		):
			result = api_mod.summarise_thread("CRM Deal", "X")
		self.assertEqual(result, {"status": "unavailable"})
		complete.assert_not_called()


class SlotRefusalRefundTest(IntegrationTestCase):
	"""A slot-refused call must not burn the day budgets either.

	_throttled charges the user and site counters before the slot can say no,
	so during a slow-model incident -- exactly when the slots fill -- each
	retry burned a daily-budget unit for a call that never reached the model,
	and the tier stayed dark after the model recovered.
	"""

	def test_a_slot_refusal_leaves_both_day_counters_where_they_were(self):
		inflight = api_mod._inflight_key()
		site_key, user_key = api_mod.budget_key(), api_mod.user_budget_key()
		for key in (inflight, site_key, user_key):
			frappe.cache().delete(key)
			self.addCleanup(frappe.cache().delete, key)
		frappe.cache().setex(inflight, 60, api_mod.MAX_CONCURRENT_MODEL_CALLS)

		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod, "user_rate_limited", return_value=False),
			mock.patch.object(api_mod.tools, "read_record", return_value={"name": "X"}),
			mock.patch.object(api_mod.tools, "read_thread", return_value=[]),
			mock.patch.object(api_mod.client, "complete") as complete,
		):
			result = api_mod.summarise_thread("CRM Deal", "X")

		self.assertEqual(result, {"status": "unavailable"})
		complete.assert_not_called()
		self.assertEqual(int(frappe.cache().get(site_key) or 0), 0)
		self.assertEqual(int(frappe.cache().get(user_key) or 0), 0)
