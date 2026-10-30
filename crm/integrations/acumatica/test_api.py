from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestHookWiring(FrappeTestCase):
	def test_sweep_is_registered_daily_long(self):
		from crm import hooks

		self.assertIn(
			"crm.integrations.acumatica.importer.schedule_sweep",
			hooks.scheduler_events["daily_long"],
		)

	def test_registered_methods_are_importable(self):
		frappe.get_attr("crm.integrations.acumatica.importer.schedule_sweep")
		frappe.get_attr("crm.integrations.acumatica.importer.nightly_sweep")
		frappe.get_attr("crm.integrations.acumatica.api.start_backfill")
		frappe.get_attr("crm.integrations.acumatica.api.get_sync_status")
		frappe.get_attr("crm.integrations.acumatica.api.test_connection")


class TestStartBackfill(FrappeTestCase):
	def setUp(self):
		# Enable the integration before each test (controller ruling)
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		frappe.db.set_single_value("CRM Acumatica Settings", "instance_url", "https://t.acumatica.com")
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def tearDown(self):
		# Disable the integration after each test (controller ruling)
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	@patch("crm.integrations.acumatica.api.frappe.enqueue")
	def test_start_backfill_enqueues_on_long_queue(self, enqueue):
		frappe.set_user("Administrator")
		from crm.integrations.acumatica.api import start_backfill

		out = start_backfill()
		self.assertTrue(out["queued"])
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		# the same id the sweep and the webhook use, so the queue holds one sync
		self.assertEqual(enqueue.call_args.kwargs["job_id"], "acumatica_sync")

	@patch("crm.integrations.acumatica.api.frappe.enqueue")
	def test_start_backfill_raises_the_job_timeout_above_the_queue_default(self, enqueue):
		"""The long queue's 1500s default kills a real tenant's first backfill,
		which writes its high-water mark only once every entity has finished."""
		frappe.set_user("Administrator")
		from crm.integrations.acumatica.api import BACKFILL_TIMEOUT, start_backfill

		start_backfill()
		self.assertEqual(enqueue.call_args.kwargs["timeout"], BACKFILL_TIMEOUT)
		self.assertGreater(BACKFILL_TIMEOUT, 1500)

	def test_start_backfill_rejects_non_managers(self):
		from crm.integrations.acumatica.api import start_backfill

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				start_backfill()
		finally:
			frappe.set_user("Administrator")


class TestSyncStatus(FrappeTestCase):
	def tearDown(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "last_sync_error", "")
		frappe.db.set_single_value("CRM Acumatica Settings", "pending_retries", "{}")
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def test_status_carries_the_new_keys(self):
		from crm.integrations.acumatica.api import get_sync_status

		frappe.db.set_single_value("CRM Acumatica Settings", "last_sync_error", "boom")
		# two NoteIDs under Customer, one under Contact -- the count is across entities
		frappe.db.set_single_value(
			"CRM Acumatica Settings",
			"pending_retries",
			'{"Customer": {"n1": 1, "n2": 2}, "Contact": {"n3": 1}}',
		)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

		out = get_sync_status()
		self.assertEqual(out["last_sync_error"], "boom")
		self.assertEqual(out["pending_retries"], 3)
		self.assertIn("last_synced_at", out)
		self.assertIn("open_issues", out)
		self.assertFalse(out["running"])

	@patch("crm.integrations.acumatica.api.is_job_enqueued")
	def test_running_reflects_the_shared_job_id(self, mock_enqueued):
		from crm.integrations.acumatica.api import SYNC_JOB_ID, get_sync_status

		mock_enqueued.return_value = True
		out = get_sync_status()
		self.assertTrue(out["running"])
		mock_enqueued.assert_called_once_with(SYNC_JOB_ID)


class TestConnection(FrappeTestCase):
	def tearDown(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "instance_url", "")
		frappe.clear_cache(doctype="CRM Acumatica Settings")
		frappe.set_user("Administrator")

	def test_rejects_non_managers(self):
		from crm.integrations.acumatica.api import test_connection

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			test_connection()

	def test_missing_instance_url_is_reported_not_thrown(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("CRM Acumatica Settings", "instance_url", "")
		from crm.integrations.acumatica.api import test_connection

		out = test_connection()
		self.assertFalse(out["ok"])
		self.assertIn("Instance URL", out["error"])

	@patch("crm.integrations.acumatica.api.AcumaticaClient")
	def test_transport_failure_is_reported_not_raised(self, MockClient):
		from crm.integrations.acumatica.api import test_connection
		from crm.integrations.acumatica.client import AcumaticaError

		frappe.set_user("Administrator")
		frappe.db.set_single_value("CRM Acumatica Settings", "instance_url", "https://t.acumatica.com")
		MockClient.return_value._cache_key.return_value = "k"
		MockClient.return_value.ping.side_effect = AcumaticaError("boom", status_code=401, body="bad creds")

		out = test_connection()
		self.assertFalse(out["ok"])
		self.assertIn("401", out["error"])

	@patch("crm.integrations.acumatica.api.AcumaticaClient")
	def test_success_returns_the_sample(self, MockClient):
		from crm.integrations.acumatica.api import test_connection

		frappe.set_user("Administrator")
		frappe.db.set_single_value("CRM Acumatica Settings", "instance_url", "https://t.acumatica.com")
		MockClient.return_value._cache_key.return_value = "k"
		MockClient.return_value.ping.return_value = {"ok": True, "sample": "C001"}

		self.assertEqual(test_connection(), {"ok": True, "sample": "C001"})

	@patch("crm.integrations.acumatica.api.AcumaticaClient")
	def test_logs_out_after_pinging_whether_or_not_it_worked(self, MockClient):
		from crm.integrations.acumatica.api import test_connection
		from crm.integrations.acumatica.client import AcumaticaError

		frappe.set_user("Administrator")
		frappe.db.set_single_value("CRM Acumatica Settings", "instance_url", "https://t.acumatica.com")
		MockClient.return_value._cache_key.return_value = "k"
		MockClient.return_value.ping.return_value = {"ok": True, "sample": "C001"}
		test_connection()
		MockClient.return_value.logout.assert_called_once()
		MockClient.return_value.ping.side_effect = AcumaticaError("boom", status_code=500, body="x")
		test_connection()
		self.assertEqual(MockClient.return_value.logout.call_count, 2)

	@patch("crm.integrations.acumatica.api.AcumaticaClient")
	def test_forces_a_fresh_token_before_pinging(self, MockClient):
		"""The operator just saved new credentials -- a cached token from the old
		ones would make the test pass or fail on stale creds instead of the new ones."""
		from crm.integrations.acumatica.api import test_connection

		frappe.set_user("Administrator")
		frappe.db.set_single_value("CRM Acumatica Settings", "instance_url", "https://t.acumatica.com")
		MockClient.return_value._cache_key.return_value = "acumatica_token::https://t.acumatica.com"
		MockClient.return_value.ping.return_value = {"ok": True, "sample": None}
		frappe.cache().set_value("acumatica_token::https://t.acumatica.com", "stale")

		test_connection()
		self.assertIsNone(frappe.cache().get_value("acumatica_token::https://t.acumatica.com"))


class TestSyncIssueEndpoints(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _record(self, remote_id):
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import record_sync_issue

		record_sync_issue("Customer", remote_id, "Import Failed", "boom")

	def test_open_issues_are_listed_and_dismissal_hides_them(self):
		from crm.integrations.acumatica.api import dismiss_sync_issue, get_open_sync_issues

		remote_id = f"ISSUE-{frappe.generate_hash(length=6)}"
		self._record(remote_id)

		mine = [row for row in get_open_sync_issues() if row["remote_id"] == remote_id]
		self.assertEqual(len(mine), 1)
		self.assertEqual(mine[0]["kind"], "Import Failed")

		# exactly what the panel posts back: the int the listing gave it. Frappe checks
		# whitelisted arguments against their annotations in tests too, so a str() here
		# would pass while every real Dismiss click answered 417.
		self.assertIsInstance(mine[0]["name"], int)
		self.assertTrue(dismiss_sync_issue(mine[0]["name"]))

		self.assertFalse([row for row in get_open_sync_issues() if row["remote_id"] == remote_id])

	def test_a_name_that_was_stringified_on_the_way_still_matches(self):
		from crm.integrations.acumatica.api import dismiss_sync_issue, get_open_sync_issues

		remote_id = f"ISSUE-{frappe.generate_hash(length=6)}"
		self._record(remote_id)
		mine = [row for row in get_open_sync_issues() if row["remote_id"] == remote_id]

		self.assertTrue(dismiss_sync_issue(str(mine[0]["name"])))

	def test_dismiss_unknown_issue_returns_false(self):
		from crm.integrations.acumatica.api import dismiss_sync_issue

		self.assertFalse(dismiss_sync_issue("-1"))

	def test_endpoints_reject_non_managers(self):
		from crm.integrations.acumatica.api import dismiss_sync_issue, get_open_sync_issues

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_open_sync_issues()
		with self.assertRaises(frappe.PermissionError):
			dismiss_sync_issue("1")


class TestMutatingEndpointsRefuseGet(FrappeTestCase):
	"""Frappe checks CSRF on unsafe methods only and rolls a GET's writes back. A
	mutating endpoint that answers GET can be fired by a link or an <img> on any page
	the user opens -- for Create Sales Quote, one more order in the client's ERP per
	visit, with the rollback discarding the OrderNbr that blocks the next one."""

	def _refused_on_get(self, fn):
		from frappe.handler import is_valid_http_method

		request = MagicMock()
		request.method = "GET"
		with patch.object(frappe.local, "request", request, create=True):
			with self.assertRaises(frappe.PermissionError):
				is_valid_http_method(fn)
		request.method = "POST"
		with patch.object(frappe.local, "request", request, create=True):
			is_valid_http_method(fn)  # the form script and the panel POST

	def test_create_sales_quote_refuses_get(self):
		from crm.integrations.acumatica.outbound import create_sales_quote_from_deal

		self._refused_on_get(create_sales_quote_from_deal)

	def test_test_connection_refuses_get(self):
		from crm.integrations.acumatica.api import test_connection

		self._refused_on_get(test_connection)

	def test_dismissing_a_sync_issue_refuses_get(self):
		from crm.fcrm.doctype.erpnext_crm_settings import erpnext_crm_settings
		from crm.integrations.acumatica.api import dismiss_sync_issue

		self._refused_on_get(dismiss_sync_issue)
		self._refused_on_get(erpnext_crm_settings.dismiss_sync_issue)


class TestFormScript(FrappeTestCase):
	def test_form_script_mentions_quote_action_and_endpoint(self):
		from crm.integrations.acumatica.api import get_crm_form_script

		script = get_crm_form_script()
		self.assertIn("Create Sales Quote", script)
		self.assertIn("crm.integrations.acumatica.outbound.create_sales_quote_from_deal", script)
		self.assertIn("crm.integrations.acumatica.api.is_enabled", script)
		self.assertNotIn("frappe.client.get_single_value", script)
		# a deal that already has its quote gets no button, not an erroring one
		self.assertIn("if (this.doc.acumatica_sales_quote) return", script)

	def test_form_script_swallows_the_settings_read_failure(self):
		"""A rep without read access on the settings would otherwise get an
		unhandled rejection on every single deal load."""
		from crm.integrations.acumatica.api import get_crm_form_script

		script = get_crm_form_script()
		self.assertIn(".catch(() => {})", script)
		self.assertIn("e.messages?.[0]", script)
