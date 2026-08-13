# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Settings doctype must exist, be a Single, and ship disabled.

Defaults are asserted against the DocType meta rather than a loaded document: an
unsaved Single has no row, so reading attributes off it proves nothing.

There is deliberately no test that loads the Single and asserts ``enabled`` is off.
That reads live, admin-mutable state, so it fails the moment somebody legitimately
turns the feature on -- and it cannot tell that apart from a fresh install shipping it
on, which is the only thing worth catching. It passed on CI only because CI never
enables anything. The property it was reaching for is asserted where it is actually
decidable: the declared default below, and ``test_config`` on the code path that reads
it (``from_settings({})`` yields ``enabled=False``, so a missing or empty row fails
closed).
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent.config import DEFAULT_SETTINGS


class AgentSettingsTest(IntegrationTestCase):
	def test_is_a_single_doctype(self):
		self.assertTrue(frappe.get_meta("CRM Agent Settings").issingle)

	def test_field_defaults_are_declared(self):
		meta = frappe.get_meta("CRM Agent Settings")
		self.assertEqual(meta.get_field("enabled").default, "0")
		self.assertEqual(meta.get_field("timeout").default, "30")
		self.assertEqual(meta.get_field("max_tokens").default, "1024")

	def test_declared_defaults_match_the_config_modules_copy(self):
		"""``config.DEFAULT_SETTINGS`` exists because an unsaved Single has no row to read
		field defaults from, so the values are written down twice. Nothing else keeps the
		two copies in step: assert every field agrees, or the flag could ship on in one
		place and off in the other."""
		meta = frappe.get_meta("CRM Agent Settings")
		self.assertEqual(len(DEFAULT_SETTINGS), 5)
		for fieldname, default in DEFAULT_SETTINGS.items():
			field = meta.get_field(fieldname)
			self.assertIsNotNone(field, f"{fieldname} is in DEFAULT_SETTINGS but not in the doctype")
			self.assertEqual(
				field.default,
				str(default),
				f"{fieldname}: doctype default {field.default!r} != DEFAULT_SETTINGS {default!r}",
			)
