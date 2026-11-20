# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The patch that moves a site off the retired default model.

It writes an admin's own settings, so the rule it must keep is narrow: replace
only a value that is exactly a default this app shipped, and nothing typed by
a person. These run against the Singles rows directly and restore what they
changed.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent.config import DEFAULT_SETTINGS, get_config
from crm.patches.v1_0.replace_retired_default_agent_model import (
	RETIRED_BASE_URL,
	RETIRED_MODELS,
	STACK_BASE_URL,
	execute,
)

SETTINGS = "CRM Agent Settings"
SHIPPED = "nemotron-3.5-bolt:e4b-q8_0"


class RetiredDefaultModelPatchTest(IntegrationTestCase):
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

	def stored(self):
		frappe.clear_cache()
		return frappe.db.get_singles_dict(SETTINGS)

	def test_the_shipped_default_is_the_one_model_the_product_serves(self):
		self.assertEqual(DEFAULT_SETTINGS["model"], SHIPPED)
		self.assertNotIn(DEFAULT_SETTINGS["model"], RETIRED_MODELS)

	def test_a_site_still_on_the_old_default_is_moved_with_its_endpoint(self):
		"""What ``create-site`` wrote from the compose file's own defaults."""
		self.store(enabled=1, model=RETIRED_MODELS[0], base_url=RETIRED_BASE_URL, max_tokens=2048)
		execute()

		stored = self.stored()
		self.assertEqual(stored["model"], SHIPPED)
		self.assertEqual(stored["base_url"], STACK_BASE_URL)
		# nothing else is this patch's to decide
		self.assertEqual(str(stored["enabled"]), "1")
		self.assertEqual(str(stored["max_tokens"]), "2048")
		self.assertEqual(get_config().model, SHIPPED)

	def test_every_default_the_app_shipped_for_it_counts(self):
		for retired in RETIRED_MODELS:
			with self.subTest(retired=retired):
				self.store(model=retired)
				execute()
				self.assertEqual(self.stored()["model"], SHIPPED)

	def test_an_endpoint_an_admin_entered_stays_when_the_model_moves(self):
		for base_url in (
			"http://localhost:11434/v1",
			"http://gpu.internal:11434/v1",
			"http://ollama:11434/v1/",
		):
			with self.subTest(base_url=base_url):
				self.store(model=RETIRED_MODELS[0], base_url=base_url)
				execute()

				stored = self.stored()
				self.assertEqual(stored["model"], SHIPPED)
				self.assertEqual(stored["base_url"], base_url)

	def test_a_model_an_admin_chose_is_left_alone_and_so_is_its_endpoint(self):
		"""Including the retired model under any name but the shipped one: another
		quantisation or another case was typed by someone."""
		for model in (
			"gpt-4o-mini",
			"hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q8_0",
			"HF.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M",
			" hf.co/LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M",
			SHIPPED,
		):
			with self.subTest(model=model):
				self.store(model=model, base_url=RETIRED_BASE_URL)
				execute()

				stored = self.stored()
				self.assertEqual(stored["model"], model)
				self.assertEqual(stored["base_url"], RETIRED_BASE_URL)

	def test_an_unsaved_single_gets_nothing_written(self):
		self.store()
		execute()
		self.assertEqual(self.stored(), {})
		self.assertEqual(get_config().model, SHIPPED)

	def test_running_it_twice_changes_nothing_more(self):
		self.store(model=RETIRED_MODELS[0], base_url=RETIRED_BASE_URL)
		execute()
		first = self.stored()
		execute()
		self.assertEqual(self.stored(), first)
