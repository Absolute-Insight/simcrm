# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Pure unit tests for config-layer pattern compilation (``config._compile_pattern``).

Fully offline: no DB, no network. Covers the word-boundary fix -- an un-anchored
short substring keyword like "erp" or "api" previously matched inside unrelated
words ("waterproofing", "capital"), causing false industry-classification hits.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.tests import UnitTestCase

from crm.domain_enrichment import config, http
from crm.domain_enrichment.config import _compile_pattern

SETTINGS_JSON = (
	Path(config.__file__).parent / "doctype" / "crm_enrichment_settings" / "crm_enrichment_settings.json"
)
LAYOUT_TYPES = {"Tab Break", "Section Break", "Column Break", "Table"}


class CompilePatternTest(UnitTestCase):
	def test_substring_pattern_does_not_match_inside_unrelated_word(self):
		erp_rx = _compile_pattern("erp", is_regex=0)
		self.assertIsNone(erp_rx.search("Industrial Adhesives, Paints and Waterproofing Solutions"))
		self.assertIsNone(erp_rx.search("enterprise value creation"))

	def test_substring_pattern_still_matches_standalone_word(self):
		erp_rx = _compile_pattern("erp", is_regex=0)
		self.assertIsNotNone(erp_rx.search("Our ERP rollout finished on schedule"))

	def test_api_pattern_does_not_match_inside_capital_or_rapid(self):
		api_rx = _compile_pattern("api", is_regex=0)
		self.assertIsNone(api_rx.search("venture capital and rapid growth"))
		self.assertIsNotNone(api_rx.search("a public REST API for developers"))

	def test_multi_word_phrase_pattern_still_matches(self):
		rx = _compile_pattern("enterprise resource planning", is_regex=0)
		self.assertIsNotNone(rx.search("our Enterprise Resource Planning suite"))

	def test_is_regex_patterns_are_left_unanchored(self):
		# An admin-authored regex (is_regex=1) is compiled as-is -- no word-boundary
		# wrapping, so existing admin patterns (e.g. social-profile URL regexes) keep
		# their exact intended behavior.
		rx = _compile_pattern(r"linkedin\.com/(company|in|school)/", is_regex=1)
		self.assertIsNotNone(rx.search("https://www.linkedin.com/company/acme"))


class SettingsReachTheEngineTest(UnitTestCase):
	"""A setting the admin can see must change something. ``_build_settings`` copies
	only the keys of ``DEFAULT_SETTINGS``, so a field missing there is dropped on the
	way to the engine without a word."""

	def _settings_fields(self):
		doctype = json.loads(SETTINGS_JSON.read_text())
		return {f["fieldname"] for f in doctype["fields"] if f["fieldtype"] not in LAYOUT_TYPES}

	def test_every_settings_field_reaches_the_config(self):
		# seed_version is the seeder's bookkeeping, not a setting
		self.assertEqual(self._settings_fields() - {"seed_version"}, set(config.DEFAULT_SETTINGS))

	def test_max_fetch_seconds_reaches_the_fetch_budget(self):
		"""Documented as the override for the per-fetch budget, it was not a settings
		key, so the budget stayed 3 x request_timeout whatever it was set to."""
		cfg = config.EnrichmentConfig(
			settings=config._build_settings(frappe._dict(request_timeout=10, max_fetch_seconds=5))
		)
		self.assertEqual(http._fetch_budget(cfg, 10), 5.0)

	def test_max_fetch_seconds_cannot_raise_the_cap(self):
		"""The budget is what keeps a synchronous preview from holding a web worker."""
		cfg = config.EnrichmentConfig(settings={"max_fetch_seconds": 600})
		self.assertEqual(http._fetch_budget(cfg, 10), float(http.MAX_FETCH_SECONDS))

	def test_the_preview_offers_no_page_count(self):
		"""The preview reads one homepage's <head> by design (``pipeline.preview``);
		"Preview Max Pages" was shown, saved, and never read."""
		self.assertNotIn("preview_max_pages", self._settings_fields())
