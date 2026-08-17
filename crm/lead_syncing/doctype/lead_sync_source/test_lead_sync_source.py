# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.lead_syncing import CONFIG_KEY, lead_syncing_enabled
from crm.lead_syncing.background_sync import sync_leads_from_all_enabled_sources

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestLeadSyncSource(IntegrationTestCase):
	"""
	Integration tests for LeadSyncSource.
	Use this class for testing interactions between multiple components.
	"""

	pass


class TestLeadSyncingDisabled(IntegrationTestCase):
	"""The connector is off by default because it loses leads -- see
	crm/lead_syncing/__init__.py. These pin the switch: a later change that
	re-enables Facebook syncing without fixing pagination has to delete a test
	to do it, rather than flipping a default nobody notices."""

	def source(self, enabled: int = 0):
		return frappe.get_doc(
			{
				"doctype": "Lead Sync Source",
				"type": "Facebook",
				"background_sync_frequency": "Hourly",
				"enabled": enabled,
			}
		)

	def test_disabled_by_default(self):
		self.assertFalse(lead_syncing_enabled())

	def test_background_sync_touches_nothing(self):
		# Not just "returns None" -- it must not even look for sources, or a
		# 5-minute cron queries the table forever for a feature that is off.
		with patch.object(frappe, "get_all") as get_all:
			for frequency in ("Every 5 Minutes", "Hourly", "Daily", None):
				self.assertIsNone(sync_leads_from_all_enabled_sources(frequency))
		get_all.assert_not_called()

	def test_enabling_a_source_is_blocked(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.source(enabled=1).validate_syncing_available()
		# The message has to say which flag turns it back on, or the only way
		# to find out is to read the source.
		self.assertIn(CONFIG_KEY, str(caught.exception))

	def test_a_disabled_source_still_saves(self):
		# An already-enabled source on an upgraded site must stay editable:
		# blocking every save would leave the admin unable to untick the box.
		self.source(enabled=0).validate_syncing_available()

	def test_manual_and_enqueued_sync_both_refuse(self):
		source = self.source()
		for method in ("sync_leads", "_sync_leads"):
			with self.subTest(method=method), self.assertRaises(frappe.ValidationError):
				getattr(source, method)()

	def test_site_config_re_enables_everything(self):
		# The escape hatch has to restore the background job too. Gating only
		# the button would leave an operator who set the flag believing leads
		# were syncing on a schedule when nothing was.
		with patch.dict(frappe.conf, {CONFIG_KEY: 1}):
			self.assertTrue(lead_syncing_enabled())
			self.source(enabled=1).validate_syncing_available()
			with patch.object(frappe, "get_all", return_value=[]) as get_all:
				sync_leads_from_all_enabled_sources("Hourly")
			get_all.assert_called_once()
