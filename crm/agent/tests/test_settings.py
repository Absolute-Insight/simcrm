# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Settings doctype must exist, be a Single, and ship disabled.

Defaults are asserted against the DocType meta rather than a loaded document: an
unsaved Single has no row, so reading attributes off it proves nothing.

There is deliberately no test that loads the Single and asserts ``enabled`` is off.
That reads live, admin-mutable state, so it fails the moment somebody legitimately
turns the feature on -- and it cannot tell that apart from a fresh install shipping it
on, which is the only thing worth catching. It passed on CI only because CI never
enables anything. The property it was reaching for is asserted where it is actually
decidable: the declared default below, and ``test_config`` on the code path that reads
it (``from_settings({})`` yields ``enabled=False``, so a missing or empty row fails
closed).
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent.config import DEFAULT_SETTINGS, SIGNAL_DEFAULTS


class AgentSettingsTest(IntegrationTestCase):
	def test_is_a_single_doctype(self):
		self.assertTrue(frappe.get_meta("CRM Agent Settings").issingle)

	def test_field_defaults_are_declared(self):
		meta = frappe.get_meta("CRM Agent Settings")
		self.assertEqual(meta.get_field("enabled").default, "0")
		self.assertEqual(meta.get_field("timeout").default, "30")
		# 2048, not 1024: the shipped default model truncates mid-object on a long
		# thread at 1024 and the reply arrives as invalid JSON.
		self.assertEqual(meta.get_field("max_tokens").default, "2048")

	def test_declared_defaults_match_the_config_modules_copy(self):
		"""``config.DEFAULT_SETTINGS`` exists because an unsaved Single has no row to read
		field defaults from, so the values are written down twice. Nothing else keeps the
		two copies in step: assert every field agrees, or the flag could ship on in one
		place and off in the other."""
		meta = frappe.get_meta("CRM Agent Settings")
		self.assertEqual(len(DEFAULT_SETTINGS), 6)
		self.assertEqual(len(SIGNAL_DEFAULTS), 6)
		for fieldname, default in {**DEFAULT_SETTINGS, **SIGNAL_DEFAULTS}.items():
			field = meta.get_field(fieldname)
			self.assertIsNotNone(field, f"{fieldname} is in the defaults but not in the doctype")
			self.assertEqual(
				field.default,
				str(default),
				f"{fieldname}: doctype default {field.default!r} != code default {default!r}",
			)

	def test_the_signal_switch_ships_on_while_the_model_tier_ships_off(self):
		"""Constraint 3: the deterministic tier works with the agent disabled. If the
		signal flag inherited the model flag's default the whole feature would ship
		dark on every site."""
		meta = frappe.get_meta("CRM Agent Settings")
		self.assertEqual(meta.get_field("enabled").default, "0")
		self.assertEqual(meta.get_field("signals_enabled").default, "1")


class BaseUrlValidationTest(IntegrationTestCase):
	"""The base URL is the target of a server-side POST that carries the API key."""

	def save_url(self, url):
		settings = frappe.get_doc("CRM Agent Settings")
		self.addCleanup(frappe.db.rollback)
		settings.base_url = url
		settings.save()

	def test_a_plausible_endpoint_is_accepted(self):
		self.save_url("http://gpu.local:8000/v1")

	def test_a_non_http_scheme_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.save_url("file:///etc/passwd")

	def test_a_url_with_no_host_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.save_url("localhost:8000/v1")


class TimeoutValidationTest(IntegrationTestCase):
	"""A call retries once, so it holds a web worker for up to twice the timeout.
	Past the proxy's read timeout the rep sees a failed request while the worker
	keeps working -- and nothing in the CRM says why."""

	def save_timeout(self, seconds):
		settings = frappe.get_doc("CRM Agent Settings")
		self.addCleanup(frappe.db.rollback)
		settings.timeout = seconds
		settings.save()

	def test_the_shipped_default_fits(self):
		self.save_timeout(30)

	def test_the_largest_safe_value_is_accepted(self):
		# 59 x 2 = 118 < 120.
		self.save_timeout(59)

	def test_one_second_over_is_refused(self):
		# 60 x 2 = 120, which is not *under* the proxy's 120.
		with self.assertRaises(frappe.ValidationError):
			self.save_timeout(60)

	def test_the_value_an_admin_would_pick_for_a_reasoning_model_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.save_timeout(300)
		# The message has to carry the number to use and the knob that raises it,
		# or the only way forward is reading the source.
		message = str(caught.exception)
		self.assertIn("59", message)
		self.assertIn("crm_proxy_read_timeout", message)

	def test_a_deployment_that_raised_its_proxy_timeout_may_raise_this(self):
		from unittest.mock import patch

		with patch.dict(frappe.conf, {"crm_proxy_read_timeout": 600}):
			self.save_timeout(299)

	def test_an_uninterpretable_proxy_setting_falls_back_to_the_shipped_one(self):
		"""Site config is hand-edited. A typo there must not silently unbound the
		limit -- that would be worse than the value it is meant to police."""
		from unittest.mock import patch

		with patch.dict(frappe.conf, {"crm_proxy_read_timeout": "soon"}):
			with self.assertRaises(frappe.ValidationError):
				self.save_timeout(300)


class EnvProvisionedConfigTest(IntegrationTestCase):
	"""A site seeded only by ``apply_endpoint_defaults`` must run on the shipped defaults.

	``as_dict()`` on a partially-saved Single coerces the unsaved Int fields to 0,
	which made ``timeout=0`` (every call's deadline already expired) and
	``daily_call_budget=0`` (uncapped) on exactly the deploy path
	``.pi/feats/agent/README.md`` documents. ``get_signal_config`` already reads
	through ``get_singles_dict`` for this reason; ``get_config`` must too.
	"""

	def setUp(self):
		super().setUp()
		self.saved = frappe.db.get_singles_dict("CRM Agent Settings")

	def tearDown(self):
		frappe.db.delete("Singles", {"doctype": "CRM Agent Settings"})
		for field, value in self.saved.items():
			frappe.db.set_single_value("CRM Agent Settings", field, value)
		frappe.clear_cache()
		super().tearDown()

	def test_a_site_seeded_only_by_env_defaults_gets_working_numbers(self):
		from crm.agent.config import get_config

		frappe.db.delete("Singles", {"doctype": "CRM Agent Settings"})
		frappe.db.set_single_value("CRM Agent Settings", "enabled", 1)
		frappe.db.set_single_value("CRM Agent Settings", "base_url", "http://model:11434/v1")
		frappe.db.set_single_value("CRM Agent Settings", "model", "test-model")
		frappe.clear_cache()

		cfg = get_config()
		self.assertTrue(cfg.enabled)
		self.assertEqual(cfg.base_url, "http://model:11434/v1")
		self.assertEqual(cfg.timeout, DEFAULT_SETTINGS["timeout"])
		self.assertEqual(cfg.max_tokens, DEFAULT_SETTINGS["max_tokens"])
		self.assertEqual(cfg.daily_call_budget, DEFAULT_SETTINGS["daily_call_budget"])
