# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The patch that moves a site off the retired model server.

It writes an admin's own settings, so the rule it must keep is narrow: act only
on a site whose model *and* endpoint are both exactly what this app shipped,
and touch nothing typed by a person. These run against the Singles rows and
the ``__Auth`` row directly and restore what they changed.
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import get_decrypted_password, remove_encrypted_password, set_encrypted_password

from crm.agent.config import DEFAULT_SETTINGS, get_config
from crm.patches.v1_0.replace_retired_default_agent_model import (
	RETIRED_BASE_URL,
	RETIRED_MODELS,
	STACK_BASE_URL,
	execute,
)

SETTINGS = "CRM Agent Settings"
SHIPPED = "nemotron-3.5-bolt:e4b-q8_0"


KEY = "sk-entered-for-the-old-endpoint"


class RetiredDefaultModelPatchTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.saved = frappe.db.get_singles_dict(SETTINGS)
		self.saved_key = self.key()

	def tearDown(self):
		frappe.db.delete("Singles", {"doctype": SETTINGS})
		for field, value in self.saved.items():
			frappe.db.set_single_value(SETTINGS, field, value)
		remove_encrypted_password(SETTINGS, SETTINGS, "api_key")
		if self.saved_key:
			set_encrypted_password(SETTINGS, SETTINGS, self.saved_key, "api_key")
		frappe.clear_cache()
		super().tearDown()

	def key(self):
		return get_decrypted_password(SETTINGS, SETTINGS, "api_key", raise_exception=False)

	def store(self, api_key=None, **values):
		frappe.db.delete("Singles", {"doctype": SETTINGS})
		remove_encrypted_password(SETTINGS, SETTINGS, "api_key")
		for field, value in values.items():
			frappe.db.set_single_value(SETTINGS, field, value)
		if api_key:
			# as a save leaves it: the mask in Singles, the secret in __Auth
			frappe.db.set_single_value(SETTINGS, "api_key", "*" * len(api_key))
			set_encrypted_password(SETTINGS, SETTINGS, api_key, "api_key")
		frappe.clear_cache()

	def stored(self):
		frappe.clear_cache()
		return frappe.db.get_singles_dict(SETTINGS)

	def test_the_shipped_default_is_the_one_model_the_product_serves(self):
		self.assertEqual(DEFAULT_SETTINGS["model"], SHIPPED)
		self.assertNotIn(DEFAULT_SETTINGS["model"], RETIRED_MODELS)

	def test_a_site_on_the_removed_model_server_is_moved_to_the_new_one(self):
		"""What ``create-site`` wrote from the compose file's own defaults."""
		self.store(enabled=1, model=RETIRED_MODELS[0], base_url=RETIRED_BASE_URL, max_tokens=2048)
		execute()

		stored = self.stored()
		self.assertEqual(stored["model"], SHIPPED)
		self.assertEqual(stored["base_url"], STACK_BASE_URL)
		# nothing else is this patch's to decide
		self.assertEqual(str(stored["enabled"]), "1")
		self.assertEqual(str(stored["max_tokens"]), "2048")
		self.assertNotIn("reasoning_off", stored)
		self.assertNotIn("api_key", stored)
		cfg = get_config()
		self.assertEqual((cfg.model, cfg.base_url), (SHIPPED, STACK_BASE_URL))

	def test_every_default_the_app_shipped_for_it_counts(self):
		for retired in RETIRED_MODELS:
			with self.subTest(retired=retired):
				self.store(model=retired, base_url=RETIRED_BASE_URL)
				execute()
				self.assertEqual(self.stored()["model"], SHIPPED)

	def test_reasoning_is_switched_back_on_for_a_model_that_obeys_the_switch(self):
		"""The old model thought whatever this said; the new one is measured to
		resist the injection corpus only with its thinking on."""
		self.store(model=RETIRED_MODELS[0], base_url=RETIRED_BASE_URL, reasoning_off=1)
		execute()

		self.assertEqual(str(self.stored()["reasoning_off"]), "0")
		self.assertFalse(get_config().reasoning_off)

	def test_a_key_entered_for_the_old_endpoint_is_not_sent_to_the_new_one(self):
		self.store(model=RETIRED_MODELS[0], base_url=RETIRED_BASE_URL, api_key=KEY)
		self.assertEqual(get_config().api_key, KEY)
		execute()

		self.assertIsNone(self.key())
		self.assertFalse(self.stored().get("api_key"))
		self.assertEqual(get_config().api_key, "")

	def test_the_warning_names_what_changed_and_never_the_key(self):
		self.store(model=RETIRED_MODELS[0], base_url=RETIRED_BASE_URL, reasoning_off=1, api_key=KEY)
		with mock.patch.object(frappe, "logger") as logger:
			execute()

		logger.return_value.warning.assert_called_once()
		message = logger.return_value.warning.call_args[0][0]
		for part in (RETIRED_MODELS[0], SHIPPED, STACK_BASE_URL, "reasoning_off -> 0", "api_key removed"):
			self.assertIn(part, message)
		self.assertNotIn(KEY, message)

	def test_an_endpoint_an_admin_entered_stays_and_so_does_its_model(self):
		"""Their server, their model -- the retired one included -- and their
		reasoning switch and key with it."""
		for base_url in (
			"http://localhost:11434/v1",
			"http://gpu.internal:11434/v1",
			"http://ollama:11434/v1/",
			"https://ollama:11434/v1",
		):
			with self.subTest(base_url=base_url):
				self.store(model=RETIRED_MODELS[0], base_url=base_url, reasoning_off=1, api_key=KEY)
				before = self.stored()
				execute()

				self.assertEqual(self.stored(), before)
				self.assertEqual(self.key(), KEY)

	def test_the_retired_model_with_no_endpoint_stored_is_left_alone(self):
		"""No stored address is not the removed profile's address."""
		self.store(model=RETIRED_MODELS[0])
		execute()
		self.assertEqual(self.stored()["model"], RETIRED_MODELS[0])

	def test_a_model_an_admin_chose_is_left_alone_on_the_old_address_too(self):
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
				self.store(model=model, base_url=RETIRED_BASE_URL, reasoning_off=1, api_key=KEY)
				before = self.stored()
				execute()

				self.assertEqual(self.stored(), before)
				self.assertEqual(self.key(), KEY)

	def test_an_unsaved_single_gets_nothing_written(self):
		self.store()
		execute()
		self.assertEqual(self.stored(), {})
		self.assertEqual(get_config().model, SHIPPED)

	def test_running_it_twice_changes_nothing_more(self):
		self.store(model=RETIRED_MODELS[0], base_url=RETIRED_BASE_URL, reasoning_off=1, api_key=KEY)
		execute()
		first = self.stored()
		execute()
		self.assertEqual(self.stored(), first)
		self.assertIsNone(self.key())
