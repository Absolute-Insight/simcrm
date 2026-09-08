# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Pure tests for config normalisation -- no database, no network.

``from_settings`` takes a plain dict so the whole client stack is testable without a
site, which is why it exists separately from ``get_config``.
"""

from __future__ import annotations

from frappe.tests import UnitTestCase

from crm.agent.config import DEFAULT_SETTINGS, SIGNAL_DEFAULTS, AgentConfig, SignalConfig


class AgentConfigTest(UnitTestCase):
	def test_empty_settings_fall_back_to_defaults(self):
		cfg = AgentConfig.from_settings({})
		self.assertFalse(cfg.enabled)
		self.assertEqual(cfg.model, DEFAULT_SETTINGS["model"])
		self.assertEqual(cfg.timeout, 30)

	def test_blank_strings_fall_back_rather_than_breaking(self):
		cfg = AgentConfig.from_settings({"base_url": "", "model": None})
		self.assertEqual(cfg.base_url, DEFAULT_SETTINGS["base_url"])
		self.assertEqual(cfg.model, DEFAULT_SETTINGS["model"])

	def test_trailing_slash_is_stripped_so_paths_join_cleanly(self):
		cfg = AgentConfig.from_settings({"base_url": "http://gpu.local:8000/v1/"})
		self.assertEqual(cfg.base_url, "http://gpu.local:8000/v1")

	def test_enabled_accepts_check_field_shapes(self):
		self.assertTrue(AgentConfig.from_settings({"enabled": 1}).enabled)
		self.assertTrue(AgentConfig.from_settings({"enabled": "1"}).enabled)
		self.assertFalse(AgentConfig.from_settings({"enabled": 0}).enabled)
		self.assertFalse(AgentConfig.from_settings({"enabled": "0"}).enabled)

	def test_malformed_numeric_values_fall_back_to_defaults(self):
		cfg = AgentConfig.from_settings({"timeout": "abc"})
		self.assertEqual(cfg.timeout, DEFAULT_SETTINGS["timeout"])
		cfg = AgentConfig.from_settings({"max_tokens": "not_a_number"})
		self.assertEqual(cfg.max_tokens, DEFAULT_SETTINGS["max_tokens"])

	def test_a_malformed_enabled_value_degrades_to_off(self):
		"""The whole module's contract is to degrade, never to raise. A bare ``int()``
		here threw a ``ValueError`` out of ``get_config()`` -- and the safe reading of an
		uninterpretable flag is off."""
		self.assertFalse(AgentConfig.from_settings({"enabled": "yes"}).enabled)
		self.assertFalse(AgentConfig.from_settings({"enabled": "true"}).enabled)
		self.assertFalse(AgentConfig.from_settings({"enabled": []}).enabled)

	def test_overrides_replace_only_what_they_name(self):
		"""Sweeping a candidate must not disturb the rest of the site's config."""
		cfg = AgentConfig.from_settings(
			{"base_url": "http://site.local/v1", "model": "shipped", "timeout": 45}
		)
		swept = cfg.with_overrides(model="candidate")
		self.assertEqual(swept.model, "candidate")
		self.assertEqual(swept.base_url, "http://site.local/v1")
		self.assertEqual(swept.timeout, 45)

	def test_an_override_is_normalised_like_a_settings_value(self):
		"""A hand-typed base_url arrives with a trailing slash as often as not, and
		``_post`` appends ``/chat/completions`` -- so the override has to go through
		the same normalisation, not straight onto the dataclass."""
		cfg = AgentConfig.from_settings({}).with_overrides(base_url="http://candidate:8080/v1/")
		self.assertEqual(cfg.base_url, "http://candidate:8080/v1")

	def test_a_numeric_override_may_arrive_as_a_string(self):
		"""``bench execute --kwargs`` is the only caller, and what it hands over
		depends on how the operator quoted it."""
		cfg = AgentConfig.from_settings({}).with_overrides(max_tokens="4096", timeout="120")
		self.assertEqual(cfg.max_tokens, 4096)
		self.assertEqual(cfg.timeout, 120)

	def test_no_overrides_is_the_config_unchanged(self):
		cfg = AgentConfig.from_settings({"base_url": "http://site.local/v1", "model": "shipped"})
		self.assertEqual(cfg.with_overrides(), cfg)

	def test_a_none_override_is_not_an_override(self):
		"""Every override is an optional keyword, so absent arrives as None and must
		not blank the configured value."""
		cfg = AgentConfig.from_settings({"model": "shipped"})
		self.assertEqual(cfg.with_overrides(model=None).model, "shipped")

	def test_an_uninterpretable_override_degrades_rather_than_raising(self):
		"""This module's contract is to degrade, and a typo in a sweep's kwargs
		must not come back as a traceback from the middle of a run."""
		cfg = AgentConfig.from_settings({"timeout": 45}).with_overrides(timeout="soon")
		self.assertEqual(cfg.timeout, DEFAULT_SETTINGS["timeout"])

	def test_a_misspelled_override_is_refused_rather_than_ignored(self):
		"""The one failure mode worse than a broken sweep is a silent one: a typo
		that leaves the site's own endpoint measured and recorded in a table as the
		candidate's. Explicit keyword parameters make Python refuse it; changing the
		signature to ``**overrides`` is the production change this test forbids."""
		cfg = AgentConfig.from_settings({"model": "shipped"})
		with self.assertRaises(TypeError):
			cfg.with_overrides(mdoel="candidate")

	def test_the_api_key_survives_an_override(self):
		"""It is decrypted once by get_config; losing it here turns an authenticated
		endpoint into an unexplained 401 halfway through a sweep."""
		cfg = AgentConfig.from_settings({"api_key": "sk-secret"}).with_overrides(model="candidate")
		self.assertEqual(cfg.api_key, "sk-secret")

	def test_the_daily_budget_has_a_default_and_survives_a_bad_value(self):
		self.assertEqual(
			AgentConfig.from_settings({}).daily_call_budget, DEFAULT_SETTINGS["daily_call_budget"]
		)
		self.assertEqual(
			AgentConfig.from_settings({"daily_call_budget": "lots"}).daily_call_budget,
			DEFAULT_SETTINGS["daily_call_budget"],
		)


class SignalConfigTest(UnitTestCase):
	"""The deterministic tier's thresholds. Unlike the model tier, these default ON:
	the signal job is the feature, and an admin who never opens the settings page
	should still get suggestions."""

	def test_an_empty_single_leaves_the_signal_job_running_on_its_defaults(self):
		cfg = SignalConfig.from_settings({})
		self.assertTrue(cfg.signals_enabled)
		self.assertEqual(cfg.idle_deal_days, SIGNAL_DEFAULTS["idle_deal_days"])
		self.assertEqual(cfg.suggestion_ttl_days, SIGNAL_DEFAULTS["suggestion_ttl_days"])

	def test_an_administrator_can_switch_the_signals_off(self):
		self.assertFalse(SignalConfig.from_settings({"signals_enabled": 0}).signals_enabled)
		self.assertFalse(SignalConfig.from_settings({"signals_enabled": "0"}).signals_enabled)

	def test_supplied_thresholds_win(self):
		cfg = SignalConfig.from_settings({"idle_deal_days": "3", "close_horizon_days": 30})
		self.assertEqual(cfg.idle_deal_days, 3)
		self.assertEqual(cfg.close_horizon_days, 30)

	def test_a_zero_or_negative_threshold_is_clamped_to_a_day(self):
		"""Zero would make the hourly job emit a suggestion for every record on the
		site, which is not what anybody meant to type."""
		cfg = SignalConfig.from_settings({"idle_deal_days": 0, "suggestion_ttl_days": -5})
		self.assertEqual(cfg.idle_deal_days, 1)
		self.assertEqual(cfg.suggestion_ttl_days, 1)

	def test_a_malformed_threshold_falls_back_rather_than_raising(self):
		cfg = SignalConfig.from_settings({"dismiss_cooldown_days": "soon"})
		self.assertEqual(cfg.dismiss_cooldown_days, SIGNAL_DEFAULTS["dismiss_cooldown_days"])
