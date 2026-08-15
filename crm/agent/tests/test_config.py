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
