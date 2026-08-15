# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Write-tier proposal layer tests.

The structural guarantee comes first: ``actions.py`` may never import frappe,
so a compromised draft has no route to the database from inside this module.
Then the endpoint's degrade paths, mirroring ``test_api``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.agent import api as api_mod
from crm.agent.config import AgentConfig
from crm.agent.context import CONTENT_START, build_reply_messages
from crm.agent.errors import AgentUnavailable
from crm.agent.schemas import ReplyDraft

DISABLED = AgentConfig(enabled=False, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)
ENABLED = AgentConfig(enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)
DRAFT = ReplyDraft(subject="Re: pricing", body="Thanks — sending the quote today.")


class ActionsNeverTouchFrappeTest(UnitTestCase):
	def test_actions_module_imports_no_frappe(self):
		source = Path(frappe.get_app_path("crm", "agent", "actions.py")).read_text()
		imported = set()
		for node in ast.walk(ast.parse(source)):
			if isinstance(node, ast.Import):
				imported.update(alias.name.split(".")[0] for alias in node.names)
			elif isinstance(node, ast.ImportFrom) and node.level == 0:
				imported.add((node.module or "").split(".")[0])
		self.assertNotIn("frappe", imported)


class ReplyContextTest(UnitTestCase):
	def test_reply_messages_fence_the_thread_and_ask_for_a_draft(self):
		messages = build_reply_messages(
			{"name": "CRM-DEAL-1", "organization": "Acme", "status": "Negotiation"},
			[{"sender": "jane@acme.test", "content": "What is the price?", "creation": "2026-08-14"}],
		)
		self.assertEqual(messages[0]["role"], "system")
		self.assertIn(CONTENT_START, messages[1]["content"])
		self.assertIn("Draft a short, professional reply", messages[1]["content"])
		self.assertIn("Do not invent commitments", messages[1]["content"])


class DraftReplyEndpointTest(IntegrationTestCase):
	def test_disabled_returns_a_status_and_never_calls_the_model(self):
		with mock.patch.object(api_mod, "get_config", return_value=DISABLED):
			with mock.patch.object(api_mod.client, "complete") as complete:
				result = api_mod.draft_reply("CRM Deal", "CRM-DEAL-0001")
		self.assertEqual(result, {"status": "disabled"})
		complete.assert_not_called()

	def test_unavailable_model_degrades_instead_of_raising(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.tools, "read_record", return_value={"name": "CRM-DEAL-0001"}),
			mock.patch.object(api_mod.tools, "read_thread", return_value=[]),
			mock.patch.object(api_mod.client, "complete", side_effect=AgentUnavailable("down")),
			mock.patch.object(api_mod, "_budget_spent", return_value=False),
		):
			result = api_mod.draft_reply("CRM Deal", "CRM-DEAL-0001")
		self.assertEqual(result["status"], "unavailable")

	def test_a_draft_comes_back_as_a_plain_dict_for_the_composer(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.tools, "read_record", return_value={"name": "CRM-DEAL-0001"}),
			mock.patch.object(api_mod.tools, "read_thread", return_value=[]),
			mock.patch.object(api_mod.client, "complete", return_value=DRAFT) as complete,
			mock.patch.object(api_mod, "_budget_spent", return_value=False),
		):
			result = api_mod.draft_reply("CRM Deal", "CRM-DEAL-0001")
		self.assertEqual(result["status"], "ok")
		self.assertEqual(result["draft"]["subject"], "Re: pricing")
		self.assertIs(complete.call_args[0][1], ReplyDraft)

	def test_the_endpoint_is_rate_limited(self):
		"""Same reasoning as ``summarise_thread``: a draft holds a worker for up to
		``timeout`` x ``MAX_ATTEMPTS``, so the per-user cap is what stands between one
		authenticated user and the worker pool."""
		self.assertTrue(hasattr(api_mod.draft_reply, "__wrapped__"))
		self.assertIsNot(api_mod.draft_reply, api_mod.draft_reply.__wrapped__)

	def test_the_endpoint_is_whitelisted(self):
		self.assertIn(api_mod.draft_reply, frappe.whitelisted)
