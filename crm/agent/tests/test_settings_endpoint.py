# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The settings page must be shown the configuration that is in force.

It used to read `frappe.client.get_value`, which returns `{}` for a Single nobody
has saved. Every field arrived undefined, so the page drew "Generate suggestions:
off" with four blank thresholds while the signal job was running happily on
SIGNAL_DEFAULTS -- and saving that screen wrote the fiction back, zeroing every
Check and Int the admin had never been shown a value for. Configuring a model
endpoint silently switched the whole suggestion engine off.

These run against the Singles rows directly, and each restores what it changed.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent.api import get_settings
from crm.agent.config import DEFAULT_SETTINGS, SIGNAL_DEFAULTS
from crm.patches.v1_0.restore_zeroed_signal_settings import THRESHOLDS
from crm.patches.v1_0.restore_zeroed_signal_settings import execute as restore_zeroed

SETTINGS = "CRM Agent Settings"


class SettingsEndpointTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.saved = frappe.db.get_singles_dict(SETTINGS)

	def tearDown(self):
		frappe.db.delete("Singles", {"doctype": SETTINGS})
		for field, value in self.saved.items():
			frappe.db.set_single_value(SETTINGS, field, value)
		frappe.clear_cache()
		super().tearDown()

	def as_unsaved(self):
		"""A Single with no stored row, the state a fresh install is in."""
		frappe.db.delete("Singles", {"doctype": SETTINGS})
		frappe.clear_cache()

	def test_an_unsaved_single_reports_the_defaults_not_blanks(self):
		"""The regression: `frappe.client.get_value` answers {} here."""
		self.as_unsaved()
		from frappe.client import get_value

		self.assertEqual(get_value(SETTINGS, '["signals_enabled"]'), {})

		settings = get_settings()
		self.assertEqual(settings["signals_enabled"], SIGNAL_DEFAULTS["signals_enabled"])
		for field, default in SIGNAL_DEFAULTS.items():
			self.assertEqual(settings[field], default, field)
		self.assertEqual(settings["base_url"], DEFAULT_SETTINGS["base_url"])
		self.assertEqual(settings["max_tokens"], DEFAULT_SETTINGS["max_tokens"])

	def test_what_it_reports_is_what_the_job_will_use(self):
		"""Not "the defaults" -- the effective config, whatever the admin has stored."""
		self.as_unsaved()
		frappe.db.set_single_value(SETTINGS, "idle_deal_days", 21)
		frappe.db.set_single_value(SETTINGS, "signals_enabled", 0)
		frappe.clear_cache()

		settings = get_settings()
		self.assertEqual(settings["idle_deal_days"], 21)
		self.assertEqual(settings["signals_enabled"], 0)
		# untouched fields still report their defaults rather than blanks
		self.assertEqual(settings["close_horizon_days"], SIGNAL_DEFAULTS["close_horizon_days"])

	def test_the_api_key_never_leaves_the_server(self):
		self.assertNotIn("api_key", get_settings())

	def test_saving_every_reported_field_back_is_a_no_op(self):
		"""What the page does on Save. Round-tripping the read must not change anything.

		This is the whole bug in one assertion: the old read handed back nothing,
		the page wrote nothing back as 0, and signals went off.
		"""
		self.as_unsaved()
		before = get_settings()

		for field, value in before.items():
			frappe.db.set_single_value(SETTINGS, field, value)
		frappe.clear_cache()

		self.assertEqual(get_settings(), before)


class RestoreZeroedSettingsPatchTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.saved = frappe.db.get_singles_dict(SETTINGS)

	def tearDown(self):
		frappe.db.delete("Singles", {"doctype": SETTINGS})
		for field, value in self.saved.items():
			frappe.db.set_single_value(SETTINGS, field, value)
		frappe.clear_cache()
		super().tearDown()

	def store(self, **values):
		frappe.db.delete("Singles", {"doctype": SETTINGS})
		for field, value in values.items():
			frappe.db.set_single_value(SETTINGS, field, value)
		frappe.clear_cache()

	def test_a_zeroed_site_gets_its_thresholds_and_its_signals_back(self):
		self.store(signals_enabled=0, **dict.fromkeys(THRESHOLDS, 0))
		restore_zeroed()
		frappe.clear_cache()

		settings = get_settings()
		for field, default in SIGNAL_DEFAULTS.items():
			self.assertEqual(settings[field], default, field)

	def test_a_deliberate_configuration_is_left_alone(self):
		"""Signals off with real thresholds is an admin's choice, not the bug."""
		self.store(signals_enabled=0, idle_deal_days=30, suggestion_ttl_days=7)
		restore_zeroed()
		frappe.clear_cache()

		settings = get_settings()
		self.assertEqual(settings["signals_enabled"], 0)
		self.assertEqual(settings["idle_deal_days"], 30)
		self.assertEqual(settings["suggestion_ttl_days"], 7)

	def test_one_zeroed_threshold_is_not_the_fingerprint(self):
		"""All four at once is what the broken write produces. One is someone typing."""
		self.store(signals_enabled=0, idle_deal_days=0, suggestion_ttl_days=14)
		restore_zeroed()
		frappe.clear_cache()

		self.assertEqual(get_settings()["signals_enabled"], 0)

	def test_an_untouched_site_is_not_written_to(self):
		frappe.db.delete("Singles", {"doctype": SETTINGS})
		frappe.clear_cache()
		restore_zeroed()
		self.assertEqual(frappe.db.get_singles_dict(SETTINGS), {})
