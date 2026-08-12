# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Pure tests for config normalisation -- no database, no network.

``from_settings`` takes a plain dict so the whole client stack is testable without a
site, which is why it exists separately from ``get_config``.
"""

from __future__ import annotations

from frappe.tests import UnitTestCase

from crm.agent.config import DEFAULT_SETTINGS, AgentConfig


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
