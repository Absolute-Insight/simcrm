# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""``ask_assistant`` endpoint tests: the knowledge-base grounding, the empty
state, the availability switch, the product catalogue toggle and the source
filter. The client is stubbed; nothing here contacts a model."""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent import api as api_mod
from crm.agent.config import AgentConfig
from crm.agent.schemas import AssistantAnswer

ENABLED = AgentConfig(enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)
WITH_PRODUCTS = AgentConfig(
	enabled=True,
	base_url="http://x/v1",
	model="m",
	timeout=5,
	max_tokens=64,
	assistant_reads_products=True,
)


def no_budget_check():
	return mock.patch.object(api_mod, "_throttled", return_value=False)


def make_article(title: str, body: str, available: int = 1, tags: str = "") -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Knowledge Article",
				"title": title,
				"category": "Test",
				"tags": tags,
				"available_to_assistant": available,
				"body": body,
			}
		)
		.insert()
		.name
	)


class AssistantApiTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("assistant_api")
		self.addCleanup(frappe.db.rollback, save_point="assistant_api")
		frappe.db.delete("CRM Knowledge Article")

	def test_an_empty_knowledge_base_reports_empty_and_never_calls_the_model(self):
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete") as complete,
			no_budget_check(),
		):
			result = api_mod.ask_assistant("what valves do we sell?")

		self.assertEqual(result, {"status": "empty"})
		complete.assert_not_called()

	def test_only_available_articles_reach_the_prompt(self):
		make_article("Gate valves", "Gate valves isolate a line. Sizes DN50 to DN600.")
		make_article("Secret pricing", "Gate valves cost a fortune.", available=0)
		answer = AssistantAnswer(answer="DN50 to DN600.", related_articles=[])
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete", return_value=answer) as complete,
			no_budget_check(),
		):
			result = api_mod.ask_assistant("what sizes do gate valves come in?")

		self.assertEqual(result["status"], "ok")
		system = complete.call_args[0][2][0]["content"]
		self.assertIn("Gate valves isolate a line", system)
		self.assertNotIn("cost a fortune", system)
		self.assertIn("Knowledge base", system)
		self.assertIs(complete.call_args[0][1], AssistantAnswer)

	def test_sources_are_filtered_to_loaded_articles_and_carry_titles(self):
		name = make_article("Ball valves", "Quarter-turn isolation.", tags="ball, quarter-turn")
		answer = AssistantAnswer(answer="Quarter-turn.", related_articles=[name, "KB-99999"])
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete", return_value=answer),
			no_budget_check(),
		):
			result = api_mod.ask_assistant("tell me about ball valves")

		self.assertEqual(result["sources"], [{"name": name, "title": "Ball valves"}])

	def test_products_join_the_prompt_only_when_the_admin_says_so(self):
		make_article("Ball valves", "Quarter-turn isolation.")
		product = frappe.get_doc(
			{
				"doctype": "CRM Product",
				"product_code": "BV-150-SS",
				"product_name": "Stainless ball valve",
				"description": "<p>Class 150 &amp; full bore</p>",
				"standard_rate": 1250,
			}
		).insert()
		self.addCleanup(frappe.delete_doc, "CRM Product", product.name, force=True)
		answer = AssistantAnswer(answer="Yes.", related_articles=[f"product:{product.name}"])

		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod.client, "complete", return_value=answer) as complete,
			no_budget_check(),
		):
			api_mod.ask_assistant("do we stock a stainless ball valve?")
		self.assertNotIn("BV-150-SS", complete.call_args[0][2][0]["content"])

		with (
			mock.patch.object(api_mod, "get_config", return_value=WITH_PRODUCTS),
			mock.patch.object(api_mod.client, "complete", return_value=answer) as complete,
			no_budget_check(),
		):
			result = api_mod.ask_assistant("do we stock a stainless ball valve?")
		system = complete.call_args[0][2][0]["content"]
		self.assertIn("BV-150-SS", system)
		# the editor's HTML is stripped and entity-decoded before the model sees it
		self.assertIn("Class 150 & full bore", system)
		self.assertNotIn("<p>", system)
		self.assertEqual(
			result["sources"], [{"name": f"product:{product.name}", "title": "Stainless ball valve"}]
		)

	def test_an_empty_question_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			api_mod.ask_assistant("  ")
