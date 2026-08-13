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
