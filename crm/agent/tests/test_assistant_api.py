# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""``ask_assistant`` endpoint tests. The client is stubbed; flags, degrade paths
and the citation filter are the subject."""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent import api as api_mod
from crm.agent.config import AgentConfig
from crm.agent.errors import AgentUnavailable
from crm.agent.schemas import AssistantAnswer

DISABLED = AgentConfig(enabled=False, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)
ENABLED = AgentConfig(enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)


def no_budget_check():
	return mock.patch.object(api_mod, "_budget_spent", return_value=False)


class FlagTest(IntegrationTestCase):
	def test_disabled_returns_a_status_and_never_calls_the_model(self):
		with mock.patch.object(api_mod, "get_config", return_value=DISABLED):
			with mock.patch.object(api_mod.client, "complete") as complete:
				result = api_mod.ask_assistant("how do quotas work?")

		self.assertEqual(result, {"status": "disabled"})
		complete.assert_not_called()

	def test_an_empty_question_is_refused_before_any_config_read(self):
		with self.assertRaises(frappe.ValidationError):
			api_mod.ask_assistant("   ")

	def test_an_exhausted_budget_degrades_and_never_calls_the_model(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod, "_budget_spent", return_value=True),
			mock.patch.object(api_mod.client, "complete") as complete,
		):
			result = api_mod.ask_assistant("hello")

		self.assertEqual(result, {"status": "unavailable"})
		complete.assert_not_called()


class DegradeTest(IntegrationTestCase):
	def test_unavailable_model_degrades_instead_of_raising(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete", side_effect=AgentUnavailable("down")),
			no_budget_check(),
		):
			result = api_mod.ask_assistant("how do quotas work?")

		self.assertEqual(result["status"], "unavailable")


class HappyPathTest(IntegrationTestCase):
	def test_returns_the_answer_and_only_real_article_citations(self):
		answer = AssistantAnswer(
			answer="Set targets in Settings → Sales Targets.",
			related_articles=["forecasting-and-targets", "made-up-article"],
		)
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete", return_value=answer) as complete,
			no_budget_check(),
		):
			result = api_mod.ask_assistant("where do I set monthly sales targets?")

		self.assertEqual(result["status"], "ok")
		self.assertEqual(result["answer"], answer.answer)
		self.assertEqual(result["related_articles"], ["forecasting-and-targets"])
		self.assertIs(complete.call_args[0][1], AssistantAnswer)
		# The grounding made it into the prompt: the system message quotes the
		# article the question is obviously about.
		messages = complete.call_args[0][2]
		self.assertEqual(messages[0]["role"], "system")
		self.assertIn("forecasting-and-targets", messages[0]["content"])

	def test_history_arrives_as_json_text_and_still_becomes_turns(self):
		answer = AssistantAnswer(answer="A monthly target per rep.")
		history = '[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]'
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete", return_value=answer) as complete,
			no_budget_check(),
		):
			api_mod.ask_assistant("what is a quota?", history=history)

		roles = [m["role"] for m in complete.call_args[0][2]]
		self.assertEqual(roles, ["system", "user", "assistant", "user"])

	def test_garbage_history_is_dropped_rather_than_raising(self):
		answer = AssistantAnswer(answer="ok")
		for garbage in ("{not json", '"a string"', {"role": "user"}):
			with (
				mock.patch.object(api_mod, "get_config", return_value=ENABLED),
				mock.patch.object(api_mod.client, "complete", return_value=answer) as complete,
				no_budget_check(),
			):
				result = api_mod.ask_assistant("q", history=garbage)
			self.assertEqual(result["status"], "ok")
			self.assertEqual([m["role"] for m in complete.call_args[0][2]], ["system", "user"])

	def test_endpoint_is_whitelisted_and_rate_limited(self):
		self.assertIn(api_mod.ask_assistant, frappe.whitelisted)
		self.assertTrue(hasattr(api_mod.ask_assistant, "__wrapped__"))

	def test_an_over_long_question_is_truncated_not_refused(self):
		answer = AssistantAnswer(answer="ok")
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete", return_value=answer) as complete,
			no_budget_check(),
		):
			api_mod.ask_assistant("q" * (api_mod.ASSISTANT_QUESTION_MAX_CHARS + 500))

		question = complete.call_args[0][2][-1]["content"]
		self.assertEqual(len(question), api_mod.ASSISTANT_QUESTION_MAX_CHARS)
