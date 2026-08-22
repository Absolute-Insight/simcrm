# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The help center's content contract.

The articles are code: the help center renders them and the assistant grounds
its answers on them, so a malformed file is a build error this suite catches —
not content that silently disappears from both surfaces.
"""

from __future__ import annotations

from frappe.tests import UnitTestCase

from crm.api.help import get_articles
from crm.help import CATEGORY_ORDER, load_articles, parse_article


class ParseArticleTest(UnitTestCase):
	def test_a_well_formed_article_parses(self):
		article = parse_article(
			"sample",
			"---\ntitle: Sample\ncategory: Getting started\norder: 3\n---\n\nBody text.\n",
		)
		self.assertEqual(
			article,
			{
				"name": "sample",
				"title": "Sample",
				"category": "Getting started",
				"order": 3,
				"content": "Body text.",
			},
		)

	def test_malformed_files_are_refused_not_skipped(self):
		cases = {
			"missing opening": "title: X\n---\nbody",
			"unclosed frontmatter": "---\ntitle: X\ncategory: Getting started\norder: 1\nbody",
			"missing required key": "---\ntitle: X\norder: 1\n---\nbody",
			"unknown category": "---\ntitle: X\ncategory: Nope\norder: 1\n---\nbody",
			"non-integer order": "---\ntitle: X\ncategory: Getting started\norder: soon\n---\nbody",
			"empty body": "---\ntitle: X\ncategory: Getting started\norder: 1\n---\n\n",
		}
		for label, text in cases.items():
			with self.subTest(label):
				self.assertRaises(ValueError, parse_article, "bad", text)

	def test_a_frontmatter_value_may_contain_a_colon(self):
		article = parse_article(
			"sample",
			"---\ntitle: Vectora: a guide\ncategory: Getting started\norder: 1\n---\nbody",
		)
		self.assertEqual(article["title"], "Vectora: a guide")


class ShippedArticlesTest(UnitTestCase):
	"""Every file that ships must load; this is the gate a bad edit fails."""

	def test_every_shipped_article_parses(self):
		articles = load_articles()
		self.assertGreaterEqual(len(articles), 10)

	def test_names_are_unique(self):
		names = [a["name"] for a in load_articles()]
		self.assertEqual(len(names), len(set(names)))

	def test_sorted_by_category_then_order(self):
		keys = [(CATEGORY_ORDER.index(a["category"]), a["order"], a["name"]) for a in load_articles()]
		self.assertEqual(keys, sorted(keys))

	def test_every_category_in_use_is_a_known_category(self):
		for article in load_articles():
			self.assertIn(article["category"], CATEGORY_ORDER)

	def test_callers_get_fresh_copies(self):
		first = load_articles()
		first[0]["content"] = "vandalised"
		self.assertNotEqual(load_articles()[0]["content"], "vandalised")

	def test_articles_are_parsed_once_per_process(self):
		from unittest import mock

		from crm import help as help_mod

		help_mod._load_articles_once.cache_clear()
		self.addCleanup(help_mod._load_articles_once.cache_clear)
		with mock.patch.object(help_mod, "parse_article", wraps=help_mod.parse_article) as parse:
			load_articles()
			first_count = parse.call_count
			load_articles()
		self.assertGreater(first_count, 0)
		self.assertEqual(parse.call_count, first_count)

	def test_a_malformed_article_is_a_clear_error_from_the_endpoint(self):
		from unittest import mock

		import frappe

		from crm.api import help as help_api

		with mock.patch.object(
			help_api, "load_articles", side_effect=ValueError("help article 'x': empty body")
		):
			with self.assertRaises(frappe.ValidationError) as caught:
				get_articles()
		self.assertIn("empty body", str(caught.exception))

	def test_the_endpoint_wraps_articles_with_the_category_order(self):
		payload = get_articles()
		self.assertEqual(payload["categories"], CATEGORY_ORDER)
		self.assertEqual(payload["articles"], load_articles())
