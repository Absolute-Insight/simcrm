# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The agent role must exist, survive being created twice, and grant nothing yet.

There are no DocPerm assertions on purpose: ``ensure_agent_role`` deliberately creates
no permission rows, because ``add_permission`` would freeze standard perms on shared
core doctypes (see the module docstring in ``crm/agent/install.py``).
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent.config import get_config
from crm.agent.install import AGENT_ROLE, ENDPOINT_ENV, apply_endpoint_defaults, ensure_agent_role


class AgentRoleTest(IntegrationTestCase):
	def test_role_is_created(self):
		ensure_agent_role()
		self.assertTrue(frappe.db.exists("Role", AGENT_ROLE))

	def test_running_twice_is_harmless(self):
		ensure_agent_role()
		ensure_agent_role()
		self.assertEqual(frappe.db.count("Role", {"name": AGENT_ROLE}), 1)

	def test_no_permissions_are_frozen_for_the_role(self):
		"""A ``Custom DocPerm`` row here means the perm loop is back, and with it the
		irreversible snapshot of standard perms on ``Contact`` and ``Communication``."""
		ensure_agent_role()
		self.assertEqual(frappe.db.count("Custom DocPerm", {"role": AGENT_ROLE}), 0)


class EndpointDefaultsTest(IntegrationTestCase):
	"""Seeding the model endpoint from the environment at install time.

	The stack ships an inference server as a sibling container, so the shipped
	``localhost`` base URL is wrong there and nothing in the image knows the
	service name. Without this the compose file pulled a model no code path
	could reach.
	"""

	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.clear_cache, doctype="CRM Agent Settings")

	def env(self, **values):
		return mock.patch.dict("os.environ", values, clear=False)

	def test_nothing_in_the_environment_writes_nothing(self):
		with mock.patch.dict("os.environ", {v: "" for v in ENDPOINT_ENV.values()}, clear=False):
			self.assertEqual(apply_endpoint_defaults(), {})

	def test_the_endpoint_is_taken_from_the_environment(self):
		with self.env(VECTORA_AGENT_BASE_URL="http://ollama:11434/v1", VECTORA_AGENT_MODEL="granite"):
			apply_endpoint_defaults()
		cfg = get_config()
		self.assertEqual(cfg.base_url, "http://ollama:11434/v1")
		self.assertEqual(cfg.model, "granite")

	def test_the_tier_can_be_switched_on_by_the_operator(self):
		with self.env(VECTORA_AGENT_ENABLED="true"):
			apply_endpoint_defaults()
		self.assertTrue(get_config().enabled)

	def test_anything_but_a_yes_leaves_the_tier_off(self):
		"""A stray value must not read as consent to contact a model."""
		for value in ("0", "false", "no", "maybe", "off"):
			with self.subTest(value=value), self.env(VECTORA_AGENT_ENABLED=value):
				apply_endpoint_defaults()
				frappe.clear_cache(doctype="CRM Agent Settings")
				self.assertFalse(get_config().enabled, value)

	def test_an_unset_variable_does_not_blank_a_configured_field(self):
		"""Half a configuration must not wipe the other half.

		An operator who sets only the model would otherwise have the base URL
		overwritten with an empty string on the next install.
		"""
		frappe.db.set_single_value("CRM Agent Settings", "base_url", "http://kept:8000/v1")
		frappe.clear_cache(doctype="CRM Agent Settings")
		with mock.patch.dict(
			"os.environ",
			{"VECTORA_AGENT_BASE_URL": "", "VECTORA_AGENT_MODEL": "granite"},
			clear=False,
		):
			applied = apply_endpoint_defaults()
		self.assertEqual(applied, {"model": "granite"})
		self.assertEqual(get_config().base_url, "http://kept:8000/v1")
