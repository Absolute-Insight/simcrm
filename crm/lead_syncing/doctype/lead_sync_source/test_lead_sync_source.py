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
	"""The connector is off by default -- see crm/lead_syncing/__init__.py.

	It was off because it dropped leads; that is fixed and covered by
	``TestFacebookPagination``. It stays off because none of it has been run
	against live Facebook. These pin the switch either way: turning Facebook
	syncing on has to be a deliberate act that deletes a test, not a default
	nobody notices."""

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


class TestFacebookPagination(IntegrationTestCase):
	"""The connector used to lose leads. These are the tests that say it does not.

	The failure was two bugs holding hands: ``fetch_leads`` read one page and
	ignored Graph's cursor, and ``sync`` then moved the watermark to ``now()``
	regardless. Either alone is survivable. Together, a form with more new leads
	than fit one page reported success and silently discarded the remainder,
	because the next run asked only for leads newer than a watermark that had
	already skipped past them.

	Graph is stubbed throughout -- there is no Facebook account here, which is
	also why the connector stays switched off.
	"""

	def setUp(self):
		super().setUp()
		self.form_id = "form-1"
		if not frappe.db.exists("CRM Lead Source", "Facebook"):
			frappe.get_doc({"doctype": "CRM Lead Source", "lead_source": "Facebook"}).insert(
				ignore_permissions=True
			)
		# A real row, because Failed Lead Sync Log links to it and a stub name
		# would fail the link check rather than the behaviour under test.
		# enabled=0, so validate_syncing_available leaves it alone; before_insert
		# reaches out to Graph for the account's pages, which is patched off --
		# nothing in this suite touches the network.
		patcher = patch(
			"crm.lead_syncing.doctype.lead_sync_source.lead_sync_source.fetch_and_store_pages_from_facebook",
			return_value=[],
		)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.source_name = (
			frappe.get_doc(
				{
					"doctype": "Lead Sync Source",
					# the doctype is autoname: prompt, so the name is ours to give
					"__newname": "fb-pagination-test",
					"type": "Facebook",
					"background_sync_frequency": "Hourly",
					"access_token": "test-token",
					"enabled": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def tearDown(self):
		frappe.db.delete("CRM Lead", {"facebook_form_id": self.form_id})
		frappe.db.delete("Failed Lead Sync Log", {"source": self.source_name})
		frappe.delete_doc("Lead Sync Source", self.source_name, force=True, ignore_missing=True)
		super().tearDown()

	def source(self, pages, last_synced_at=None):
		"""A FacebookSyncSource whose Graph API is the given list of responses."""
		from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

		src = FacebookSyncSource("token", self.form_id, source_name=self.source_name)
		self.requested = []
		self.written = []

		def fake_page(url, params=None):
			self.requested.append(url)
			return pages[len(self.requested) - 1]

		src.fetch_page = fake_page
		src.get_form_questions_mapping = lambda: {"full_name": "first_name"}
		src.__dict__["_last_synced_at"] = last_synced_at
		type(src).last_synced_at = property(lambda self: self.__dict__.get("_last_synced_at"))
		src.update_last_synced_at = lambda handled_through=None: self.written.append(handled_through)
		return src

	@staticmethod
	def lead(lead_id, created_time, name="Ada"):
		return {
			"id": lead_id,
			"created_time": created_time,
			"field_data": [{"name": "full_name", "values": [name]}],
		}

	@staticmethod
	def page(leads, next_url=None):
		body = {"data": leads}
		if next_url:
			body["paging"] = {"next": next_url}
		return body

	NEXT = "https://graph.facebook.com/v23.0/form-1/leads?after=cursor2"

	def test_every_page_is_read_not_just_the_first(self):
		"""The bug, directly: page two existed and was never asked for."""
		src = self.source(
			[
				self.page([self.lead("1", "2026-08-01T10:00:00+0000")], next_url=self.NEXT),
				self.page([self.lead("2", "2026-08-01T11:00:00+0000")]),
			]
		)
		self.assertEqual([lead["id"] for lead in src.fetch_leads()], ["1", "2"])
		self.assertEqual(len(self.requested), 2)

	def test_paging_stops_when_facebook_stops_offering_a_cursor(self):
		src = self.source([self.page([self.lead("1", "2026-08-01T10:00:00+0000")])])
		list(src.fetch_leads())
		self.assertEqual(len(self.requested), 1)

	def test_a_cursor_pointing_off_facebook_is_refused(self):
		"""The cursor is a URL out of a response body and it carries the page
		access token. Following one elsewhere would hand the token over."""
		src = self.source(
			[self.page([self.lead("1", "2026-08-01T10:00:00+0000")], next_url="https://evil.test/leads")]
		)
		from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

		src.fetch_page = FacebookSyncSource.fetch_page.__get__(src)
		with patch(
			"crm.lead_syncing.doctype.lead_sync_source.facebook.graph_get",
			return_value=self.page([], next_url="https://evil.test/leads"),
		):
			with self.assertRaises(frappe.ValidationError):
				list(src.fetch_leads())

	def test_the_watermark_stops_at_the_newest_lead_handled(self):
		"""Never now(). now() is what claimed the unread pages were imported."""
		src = self.source(
			[
				self.page(
					[
						self.lead("1", "2026-08-01T10:00:00+0000"),
						self.lead("2", "2026-08-01T12:00:00+0000"),
					]
				)
			]
		)
		src.sync()
		self.assertEqual(self.written, ["2026-08-01T12:00:00+0000"])

	def test_a_run_that_fetched_nothing_leaves_the_watermark_alone(self):
		src = self.source([self.page([])])
		src.sync()
		self.assertEqual(self.written, [None])

	def test_a_failure_on_a_later_page_keeps_what_the_earlier_ones_imported(self):
		"""The watermark lands on the last lead actually handled, so the next run
		resumes there instead of either re-importing everything or skipping the
		rest."""

		def explode(url, params=None):
			self.requested.append(url)
			if len(self.requested) == 1:
				return self.page([self.lead("1", "2026-08-01T10:00:00+0000")], next_url=self.NEXT)
			raise OSError("graph went away")

		src = self.source([])
		src.fetch_page = explode
		with self.assertRaises(OSError):
			src.sync()
		self.assertEqual(self.written, ["2026-08-01T10:00:00+0000"])

	def test_the_watermark_is_set_a_second_behind_so_a_same_second_lead_is_not_lost(self):
		"""time_created is second-granular and the filter is strictly greater, so
		a lead created in the same second as the last one seen would never be
		asked for. The overlap is deliberate; already_imported absorbs it."""
		from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

		src = FacebookSyncSource("token", self.form_id, source_name=self.source_name)
		with patch.object(frappe.db, "set_value") as set_value:
			src.update_last_synced_at("2026-08-01T12:00:00+0000")
		written = set_value.call_args.args[3]
		self.assertEqual(written.strftime("%Y-%m-%d %H:%M:%S"), "2026-08-01 11:59:59")

	def test_nothing_handled_writes_no_watermark_at_all(self):
		"""Not "writes now()", which was the bug -- writes nothing. A run that
		fetched no leads must leave the mark exactly where the last one left it."""
		from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

		src = FacebookSyncSource("token", self.form_id, source_name=self.source_name)
		with patch.object(frappe.db, "set_value") as set_value:
			src.update_last_synced_at(None)
		set_value.assert_not_called()

	def test_an_already_imported_lead_is_skipped_without_a_log_line(self):
		"""The overlap re-offers the last lead every run. Logging it as a
		duplicate each time would bury the real duplicates."""
		from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

		src = FacebookSyncSource("token", self.form_id, source_name=self.source_name)
		src.get_form_questions_mapping = lambda: {"full_name": "first_name"}
		lead = self.lead("dup-1", "2026-08-01T10:00:00+0000")

		self.assertIsNotNone(src.sync_single_lead(lead))
		before = frappe.db.count("Failed Lead Sync Log", {"source": self.source_name})

		self.assertIsNone(src.sync_single_lead(lead))
		self.assertEqual(frappe.db.count("Failed Lead Sync Log", {"source": self.source_name}), before)
		self.assertEqual(frappe.db.count("CRM Lead", {"facebook_lead_id": "dup-1"}), 1)
