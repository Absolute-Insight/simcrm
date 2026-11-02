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

	@patch("crm.integrations.acumatica.client.requests.get")
	@patch("crm.integrations.acumatica.client.requests.post")
	def test_pings_on_a_login_of_its_own_and_ends_only_that_one(self, rpost, rget):
		"""The operator just saved new credentials, so the cached token -- the running
		sync's -- must not be what gets tested. Deleting it from the cache used to be
		how: that never ended the sync's login, the sync minted another, and the
		dropped one held one of the API user's concurrent-login slots for an hour."""
		from crm.integrations.acumatica.api import test_connection

		frappe.set_user("Administrator")
		frappe.db.set_single_value("CRM Acumatica Settings", "instance_url", "https://t.acumatica.com")
		key = "acumatica_token::https://t.acumatica.com"
		frappe.cache().set_value(key, "T-SYNC")  # a sync is running on this login
		self.addCleanup(frappe.cache().delete_value, key)

		def post(url, data=None, headers=None, timeout=None, **kw):
			resp = MagicMock(status_code=200)
			resp.json.return_value = {"access_token": "T-TEST", "expires_in": 3600}
			return resp

		rpost.side_effect = post
		rget.return_value = MagicMock(status_code=200)
		rget.return_value.json.return_value = [{"CustomerID": {"value": "C001"}}]

		self.assertEqual(test_connection(), {"ok": True, "sample": "C001"})

		self.assertEqual(rget.call_args.kwargs["headers"]["Authorization"], "Bearer T-TEST")
		logouts = [c for c in rpost.call_args_list if c.args[0].endswith("/entity/auth/logout")]
		self.assertEqual([c.kwargs["headers"]["Authorization"] for c in logouts], ["Bearer T-TEST"])
		# the sync's login is still the shared one, and still alive
		self.assertEqual(frappe.cache().get_value(key), "T-SYNC")


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


def _enable_push():
	s = frappe.get_doc("CRM Acumatica Settings")
	s.enabled = 1
	s.instance_url = "https://t.acumatica.com"
	s.create_customer_on_status_change = 1
	s.deal_status = "Won"
	s.new_customer_class = "COD"
	s.save(ignore_permissions=True)
	frappe.clear_cache(doctype="CRM Acumatica Settings")


def _org(name=None, customer_id=None):
	org = frappe.get_doc(
		{"doctype": "CRM Organization", "organization_name": name or f"Res-{frappe.generate_hash(length=8)}"}
	).insert(ignore_permissions=True)
	if customer_id:
		frappe.db.set_value("CRM Organization", org.name, "acumatica_id", customer_id)
	return org


def _duplicate_issue(org_name, reasons=("same name",), customer_id="C-A00400"):
	from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import record_sync_issue

	record_sync_issue(
		"Customer",
		org_name,
		"Possible Duplicate",
		"not created in Acumatica: may already be ...",
		[
			{
				"customer_id": customer_id,
				"organization": None,
				"organization_name": "Someone",
				"reasons": list(reasons),
			}
		],
	)


def _open(org_name):
	return [
		row
		for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
		if row.remote_id == org_name and not row.dismissed
	]


class TestDuplicateResolution(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_enable_push()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def _sales_user(self):
		email = f"res-rep-{frappe.generate_hash(length=6)}@example.com"
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Rep", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")
		return email

	@patch("crm.integrations.acumatica.api.AcumaticaClient")
	def test_link_existing_customer_links_the_org_and_its_deals(self, ClientCls):
		from crm.integrations.acumatica.api import get_open_sync_issues, link_existing_customer

		ClientCls.return_value.get_page.return_value = [
			{"CustomerID": {"value": "C-A00400"}, "NoteID": {"value": "g-400"}}
		]
		org = _org()
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org.name, "status": "Qualification"})
		deal.insert(ignore_permissions=True)
		_duplicate_issue(org.name)
		listed = [row for row in get_open_sync_issues() if row["remote_id"] == org.name]
		self.assertEqual(listed[0]["candidates"][0]["customer_id"], "C-A00400")

		out = link_existing_customer(org.name, "C-A00400")

		self.assertEqual(out["customer_id"], "C-A00400")
		self.assertEqual(
			frappe.db.get_value("CRM Organization", org.name, ["acumatica_id", "acumatica_noteid"]),
			("C-A00400", "g-400"),
		)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "acumatica_customer"), "C-A00400")
		self.assertEqual(_open(org.name), [])
		self.assertEqual(
			ClientCls.return_value.get_page.call_args.kwargs["filter"], "CustomerID eq 'C-A00400'"
		)

	@patch("crm.integrations.acumatica.api.AcumaticaClient")
	def test_link_refuses_a_code_acumatica_does_not_have(self, ClientCls):
		from crm.integrations.acumatica.api import link_existing_customer

		ClientCls.return_value.get_page.return_value = []
		org = _org()
		with self.assertRaises(frappe.ValidationError):
			link_existing_customer(org.name, "C-NOPE")
		self.assertFalse(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"))

	@patch("crm.integrations.acumatica.api.AcumaticaClient")
	def test_link_refuses_a_code_another_organization_holds(self, ClientCls):
		from crm.integrations.acumatica.api import link_existing_customer

		holder = _org(customer_id="C-HELD1")
		org = _org()
		with self.assertRaises(frappe.ValidationError) as caught:
			link_existing_customer(org.name, "C-HELD1")
		self.assertIn(holder.name, str(caught.exception))
		ClientCls.assert_not_called()

	@patch("crm.integrations.acumatica.api.AcumaticaClient")
	def test_link_refuses_a_malformed_code_before_any_request(self, ClientCls):
		from crm.integrations.acumatica.api import link_existing_customer

		org = _org()
		for bad in ("", "C' or 1 eq 1", "x" * 40, "-lead"):
			with self.assertRaises(frappe.ValidationError):
				link_existing_customer(org.name, bad)
		ClientCls.assert_not_called()

	def test_link_refuses_an_unknown_organization(self):
		from crm.integrations.acumatica.api import link_existing_customer

		with self.assertRaises(frappe.DoesNotExistError):
			link_existing_customer("No Such Org 9f8e7d", "C-A00400")

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_confirm_new_customer_marks_it_and_queues_the_push(self, enqueue):
		from crm.integrations.acumatica.api import confirm_new_customer

		org = _org()
		frappe.flags.in_demo_seed = True  # keep the insert's own hook out of the count
		try:
			deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org.name, "status": "Won"})
			deal.insert(ignore_permissions=True)
		finally:
			frappe.flags.in_demo_seed = False
		_duplicate_issue(org.name)
		enqueue.reset_mock()

		out = confirm_new_customer(org.name)

		self.assertTrue(out["queued"])
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_confirmed_new"), 1)
		self.assertEqual(_open(org.name), [])
		pushes = [
			c for c in enqueue.call_args_list if c.kwargs.get("job_id") == f"acumatica_customer_{org.name}"
		]
		self.assertEqual(len(pushes), 1)
		self.assertEqual(pushes[0].kwargs["deal"], deal.name)

	def test_confirm_refuses_past_a_same_vat_match(self):
		from crm.integrations.acumatica.api import confirm_new_customer

		org = _org()
		_duplicate_issue(org.name, reasons=("same VAT number", "same name"))
		with self.assertRaises(frappe.ValidationError):
			confirm_new_customer(org.name)
		self.assertFalse(frappe.db.get_value("CRM Organization", org.name, "acumatica_confirmed_new"))

	def test_confirm_refuses_a_linked_organization(self):
		from crm.integrations.acumatica.api import confirm_new_customer

		org = _org(customer_id="C-LINKED9")
		with self.assertRaises(frappe.ValidationError):
			confirm_new_customer(org.name)

	@patch("crm.integrations.acumatica.api.AcumaticaClient")
	def test_a_sales_user_may_do_neither(self, ClientCls):
		from crm.integrations.acumatica.api import confirm_new_customer, link_existing_customer

		org = _org()
		frappe.set_user(self._sales_user())
		with self.assertRaises(frappe.PermissionError):
			link_existing_customer(org.name, "C-A00400")
		with self.assertRaises(frappe.PermissionError):
			confirm_new_customer(org.name)
		frappe.set_user("Administrator")
		ClientCls.assert_not_called()
		self.assertFalse(frappe.db.get_value("CRM Organization", org.name, "acumatica_confirmed_new"))

	def test_both_refuse_get(self):
		from crm.integrations.acumatica.api import confirm_new_customer, link_existing_customer

		TestMutatingEndpointsRefuseGet._refused_on_get(self, link_existing_customer)
		TestMutatingEndpointsRefuseGet._refused_on_get(self, confirm_new_customer)
