# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

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

	def test_a_lead_logged_as_a_duplicate_is_not_logged_again_on_every_run(self):
		"""The overlap re-offers the newest lead every run. When that lead was
		logged instead of imported, matching on CRM Lead alone cannot see it, so it
		was logged again on every scheduled run -- 288 rows a day at five minutes."""
		from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

		# the same person fills the form twice: the second is a real duplicate
		leads = [
			self.lead("fb-1", "2026-08-01T10:00:00+0000"),
			self.lead("fb-2", "2026-08-01T12:00:00+0000"),
		]
		for _run in range(3):
			src = FacebookSyncSource("token", self.form_id, source_name=self.source_name)
			src.get_form_questions_mapping = lambda: {"full_name": "first_name"}
			src.fetch_leads = lambda: iter(leads)
			src.update_last_synced_at = lambda handled_through=None: None
			src.sync()

		logs = frappe.get_all("Failed Lead Sync Log", filters={"source": self.source_name}, pluck="name")
		self.assertEqual(len(logs), 1, "the same Facebook lead was logged once per run")
		self.assertEqual(
			frappe.db.get_value("Failed Lead Sync Log", logs[0], ["type", "facebook_lead_id"]),
			("Duplicate", "fb-2"),
		)

	def test_a_logged_lead_can_still_be_retried(self):
		"""Retry Sync on the log goes through sync_single_lead; the log row it
		starts from must not be what stops it."""
		from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

		src = FacebookSyncSource("token", self.form_id, source_name=self.source_name)
		src.get_form_questions_mapping = lambda: {"full_name": "first_name"}
		lead = self.lead("fb-retry", "2026-08-01T10:00:00+0000")
		src.create_failure_log(lead)

		self.assertIsNotNone(src.sync_single_lead(lead, raise_exception=True))
		self.assertEqual(frappe.db.count("CRM Lead", {"facebook_lead_id": "fb-retry"}), 1)

	def test_the_watermark_reaches_graph_to_the_second_in_utc(self):
		"""The mark is UTC wall time to the second. Sent as midnight in the worker's
		OS zone, every run re-read the whole day, and west of UTC the floor landed
		after the mark, so a lead in between was never asked for."""
		from datetime import datetime, timezone

		src = self.source([], last_synced_at=datetime(2026, 8, 1, 0, 59, 59))
		sent = []
		src.fetch_page = lambda url, params=None: sent.append(params) or self.page([])
		list(src.fetch_leads())

		floor = frappe.parse_json(sent[0]["filtering"])[0]["value"]
		self.assertEqual(floor, int(datetime(2026, 8, 1, 0, 59, 59, tzinfo=timezone.utc).timestamp()))

	def test_the_watermark_is_stored_as_utc_wall_time(self):
		"""Read back as UTC, so it has to be written as UTC: Graph's offset is
		applied, not kept on a value the Datetime column would drop it from."""
		from crm.lead_syncing.doctype.lead_sync_source.facebook import FacebookSyncSource

		src = FacebookSyncSource("token", self.form_id, source_name=self.source_name)
		with patch.object(frappe.db, "set_value") as set_value:
			src.update_last_synced_at("2026-08-01T14:00:00+0200")
		written = set_value.call_args.args[3]
		self.assertIsNone(written.tzinfo)
		self.assertEqual(written.strftime("%Y-%m-%d %H:%M:%S"), "2026-08-01 11:59:59")


class TestFacebookPagesAndFormsPaging(IntegrationTestCase):
	"""Graph pages ``/me/accounts`` and ``leadgen_forms`` the same way it pages
	leads. Read from the first page only, a form further down could never be
	picked as a Lead Sync Source."""

	NEXT = "https://graph.facebook.com/v23.0/page-1/leadgen_forms?after=CURSOR"

	def graph(self, pages):
		from crm.lead_syncing.doctype.lead_sync_source import facebook

		self.requests = []

		def fake(url, params=None):
			self.requests.append((url, params))
			return pages[url] if url in pages else pages["first"]

		return patch.object(facebook, "graph_get", side_effect=fake)

	def test_every_page_of_lead_forms_is_stored(self):
		from crm.lead_syncing.doctype.lead_sync_source import facebook

		pages = {
			"first": {
				"data": [{"id": "form-a", "name": "Spring", "questions": []}],
				"paging": {"next": self.NEXT},
			},
			self.NEXT: {"data": [{"id": "form-b", "name": "Autumn", "questions": []}]},
		}
		with self.graph(pages), patch.object(facebook, "create_facebook_lead_form_in_db") as create:
			forms = facebook.fetch_and_store_leadgen_forms_from_facebook("page-1", "page-token")

		self.assertEqual([form["id"] for form in forms], ["form-a", "form-b"])
		self.assertEqual([c.args[0]["id"] for c in create.call_args_list], ["form-a", "form-b"])
		# the cursor carries the query, not the credential: that goes again explicitly
		self.assertEqual(self.requests[1], (self.NEXT, {"access_token": "page-token"}))

	def test_every_page_of_accounts_is_read(self):
		from crm.lead_syncing.doctype.lead_sync_source import facebook

		next_url = "https://graph.facebook.com/v23.0/me/accounts?after=CURSOR"
		pages = {
			"first": {"data": [{"id": "page-1", "access_token": "p1"}], "paging": {"next": next_url}},
			next_url: {"data": [{"id": "page-2", "access_token": "p2"}]},
		}
		with (
			self.graph(pages),
			patch.object(facebook, "get_fb_account_details", return_value={"id": "acct-1"}),
			patch.object(facebook, "create_facebook_page_in_db"),
			patch.object(facebook, "fetch_and_store_leadgen_forms_from_facebook", return_value=[]),
		):
			pages_read = facebook.fetch_and_store_pages_from_facebook("user-token")

		self.assertEqual([page["id"] for page in pages_read], ["page-1", "page-2"])

	def test_a_forms_cursor_pointing_off_facebook_is_refused(self):
		"""The cursor is a URL out of a response body and the page token goes with it."""
		from crm.lead_syncing.doctype.lead_sync_source import facebook

		pages = {"first": {"data": [], "paging": {"next": "https://evil.test/forms"}}}
		with self.graph(pages), self.assertRaises(frappe.ValidationError):
			facebook.fetch_and_store_leadgen_forms_from_facebook("page-1", "page-token")
		self.assertEqual(len(self.requests), 1)


class GraphTokenHandlingTest(IntegrationTestCase):
	"""The page access token must reach Graph and nowhere else."""

	def test_the_token_travels_as_a_header_not_in_the_url(self):
		from crm.lead_syncing.doctype.lead_sync_source import facebook

		session = MagicMock()
		session.get.return_value.json.return_value = {"data": []}
		with patch.object(facebook, "get_request_session", return_value=session):
			facebook.graph_get(
				"https://graph.facebook.com/v23.0/me", params={"access_token": "tok-1", "fields": "id"}
			)

		_, kwargs = session.get.call_args
		self.assertEqual(kwargs["headers"], {"Authorization": "Bearer tok-1"})
		self.assertNotIn("access_token", kwargs["params"])
		self.assertEqual(kwargs["params"], {"fields": "id"})

	def test_a_failed_call_never_logs_the_token(self):
		from requests import HTTPError

		from crm.lead_syncing.doctype.lead_sync_source import facebook

		session = MagicMock()
		session.get.return_value.raise_for_status.side_effect = HTTPError(
			"400 Client Error: Bad Request for url: https://graph.facebook.com/v23.0/x/leads?access_token=tok-2&limit=1"
		)
		with (
			patch.object(facebook, "get_request_session", return_value=session),
			patch.object(frappe, "log_error") as log_error,
		):
			with self.assertRaises(HTTPError):
				facebook.graph_get(
					"https://graph.facebook.com/v23.0/x/leads?access_token=tok-2&limit=1",
					params={"access_token": "tok-2"},
				)

		logged = " ".join(str(v) for v in log_error.call_args.kwargs.values())
		self.assertNotIn("tok-2", logged)
		self.assertIn("access_token=***", logged)
