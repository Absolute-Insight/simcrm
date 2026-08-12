# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Settings doctype must exist, be a Single, and ship disabled.

Defaults are asserted against the DocType meta rather than a loaded document: an
unsaved Single has no row, so reading attributes off it proves nothing.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase


class AgentSettingsTest(IntegrationTestCase):
	def test_is_a_single_doctype(self):
		self.assertTrue(frappe.get_meta("CRM Agent Settings").issingle)

	def test_ships_disabled(self):
		settings = frappe.get_cached_doc("CRM Agent Settings")
		self.assertFalse(int(settings.enabled or 0))

	def test_field_defaults_are_declared(self):
		meta = frappe.get_meta("CRM Agent Settings")
		self.assertEqual(meta.get_field("enabled").default, "0")
		self.assertEqual(meta.get_field("timeout").default, "30")
		self.assertEqual(meta.get_field("max_tokens").default, "1024")
