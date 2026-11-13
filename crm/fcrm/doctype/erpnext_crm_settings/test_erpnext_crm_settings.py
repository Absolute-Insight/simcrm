# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""The SIMERP integration's save path, permissions and sync-issue dismissal.

The customer push used to run inside the CRM Deal ``on_update`` hook: three HTTP
round trips at 5s connect / 30s read, on every save of a deal sitting on the trigger
status, with any failure raised into the rep's save. These tests pin the shape that
replaced it -- a cheap check that enqueues after commit, and a worker that records a
failure instead of losing the edit.
"""

from unittest.mock import patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.erpnext_crm_settings import erpnext_crm_settings as erp

REP = "erpsettings-rep@crmtest.test"


def _enable(**overrides):
	"""Turn the integration on WITHOUT saving the singleton.

	``validate()`` creates custom fields, adds property setters and -- in remote mode
	-- calls the other site over HTTP, none of which a test of the trigger shape has
	any use for. The hook reads the values with ``frappe.get_single``, so writing
	them straight to the Singles table is enough.
	"""
	values = {
		"enabled": 1,
		"create_customer_on_status_change": 1,
		"deal_status": "Won",
		"is_erpnext_in_different_site": 1,
		"erpnext_site_url": "https://erp.invalid",
		"erpnext_company": "Test Co",
		"last_customer_push_error": "",
	}
	values.update(overrides)
	for field, value in values.items():
		frappe.db.set_single_value("ERPNext CRM Settings", field, value)
	frappe.clear_document_cache("ERPNext CRM Settings", "ERPNext CRM Settings")


def _won_deal():
	org = frappe.get_doc(
		{"doctype": "CRM Organization", "organization_name": f"Erp-{frappe.generate_hash(length=8)}"}
	).insert(ignore_permissions=True)
	return frappe.get_doc({"doctype": "CRM Deal", "organization": org.name, "status": "Won"}).insert(
		ignore_permissions=True
	)


class CustomerPushOffTheSavePathTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		_enable()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		# Leave the site with the integration off even if something above committed:
		# every later CRM Deal test record would otherwise try to reach the ERP.
		frappe.db.set_single_value("ERPNext CRM Settings", "enabled", 0)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.clear_document_cache("ERPNext CRM Settings", "ERPNext CRM Settings")
		super().tearDown()

	def test_the_deal_save_enqueues_the_push_instead_of_calling_the_erp(self):
		deal = _won_deal()
		with patch.object(erp.frappe, "enqueue") as enqueue:
			erp.create_customer_in_erpnext(deal, "on_update")

		enqueue.assert_called_once()
		self.assertEqual(
			enqueue.call_args.args[0],
			"crm.fcrm.doctype.erpnext_crm_settings.erpnext_crm_settings.push_customer_for_deal",
		)
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertEqual(enqueue.call_args.kwargs["job_id"], f"erpnext_customer_{deal.organization}")

	def test_a_deal_that_already_has_a_customer_is_not_pushed_again(self):
		deal = _won_deal()
		deal.erpnext_customer = "CUST-0001"
		with patch.object(erp.frappe, "enqueue") as enqueue:
			erp.create_customer_in_erpnext(deal, "on_update")

		enqueue.assert_not_called()

	def test_an_unreachable_erp_leaves_the_reps_save_successful(self):
		"""The whole point of the fix. Inline, this raised
		"Error while creating customer in ERPNext" out of on_update and the rep lost
		the edit -- after waiting out the connect and read timeouts."""
		with patch.object(
			erp, "get_erpnext_site_client", side_effect=requests.ConnectionError("erp is down")
		):
			deal = _won_deal()  # must not raise

		self.assertTrue(frappe.db.exists("CRM Deal", deal.name))

	def test_the_worker_records_a_failure_instead_of_raising(self):
		deal = _won_deal()
		with patch.object(
			erp, "create_customer_from_deal", side_effect=requests.ConnectionError("erp is down")
		):
			erp.push_customer_for_deal(deal.name)  # must not raise

		recorded = frappe.db.get_single_value("ERPNext CRM Settings", "last_customer_push_error")
		self.assertIn(deal.name, recorded)
		self.assertIn("erp is down", recorded)

	def test_the_worker_rechecks_the_status_before_pushing(self):
		"""Time passes between the hook and the job; the deal may have moved on."""
		deal = _won_deal()
		frappe.db.set_value("CRM Deal", deal.name, "status", "Negotiation")
		with patch.object(erp, "create_customer_from_deal") as push:
			erp.push_customer_for_deal(deal.name)

		push.assert_not_called()

	def test_a_successful_push_clears_an_older_error(self):
		frappe.db.set_single_value("ERPNext CRM Settings", "last_customer_push_error", "an older failure")
		_enable(last_customer_push_error="an older failure")
		deal = _won_deal()
		with patch.object(erp, "create_customer_from_deal", return_value="CUST-0002"):
			erp.push_customer_for_deal(deal.name)

		self.assertFalse(frappe.db.get_single_value("ERPNext CRM Settings", "last_customer_push_error"))


class QuotationUrlTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		_enable(erpnext_company="Smith & Sons #2 Co")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_every_value_reaches_erpnext_whole(self):
		"""The query string was joined by hand: "Smith & Sons" arrived as "Smith " and a
		"#" cut off everything after it, prefilling the quotation with half a party."""
		from urllib.parse import parse_qs, urlsplit

		deal = _won_deal()
		with patch.object(erp, "create_prospect_in_remote_site", return_value="Smith & Sons #1"):
			url = erp.get_quotation_url(deal.name)

		parts = urlsplit(url)
		self.assertEqual(
			f"{parts.scheme}://{parts.netloc}{parts.path}", "https://erp.invalid/app/quotation/new"
		)
		query = parse_qs(parts.query)
		self.assertEqual(query["party_name"], ["Smith & Sons #1"])
		self.assertEqual(query["company"], ["Smith & Sons #2 Co"])
		self.assertEqual(query["crm_deal"], [deal.name])
		self.assertEqual(query["quotation_to"], ["Prospect"])


class SyncIssueDismissalTest(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def _append_issue(self):
		settings = frappe.get_single("ERPNext CRM Settings")
		settings.append("sync_issues", {"kind": "unlinked_orphan", "detail": "nobody claimed it"})
		settings.flags.ignore_validate = True
		settings.save(ignore_permissions=True)
		return frappe.get_single("ERPNext CRM Settings").sync_issues[-1]

	def test_an_issue_is_dismissable_by_the_name_the_client_sends(self):
		"""Child rows autoincrement, so ``issue.name`` is an int, and the Logs tab posts
		it back as a JSON number. Frappe checks whitelisted arguments against their
		annotations in tests too: a ``str`` annotation answered every real click with
		a 417, while a test that str()-ed the name first passed."""
		issue = self._append_issue()
		self.assertIsInstance(issue.name, int)

		self.assertTrue(erp.dismiss_sync_issue(issue.name))

		dismissed = {
			str(row.name): row.dismissed for row in frappe.get_single("ERPNext CRM Settings").sync_issues
		}
		self.assertEqual(dismissed[str(issue.name)], 1)

	def test_an_unknown_issue_is_reported_rather_than_silently_accepted(self):
		self.assertFalse(erp.dismiss_sync_issue("-1"))

	def test_a_rep_cannot_dismiss_issues(self):
		issue = self._append_issue()
		if not frappe.db.exists("User", REP):
			frappe.get_doc(
				{"doctype": "User", "email": REP, "first_name": "Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True).add_roles("Sales User")
		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			erp.dismiss_sync_issue(str(issue.name))


class SettingsSecretsTest(IntegrationTestCase):
	"""The singleton holds the ERP's API key and site URL, so a rep must not read it --
	and the Deal form script must not need to."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", REP):
			frappe.get_doc(
				{"doctype": "User", "email": REP, "first_name": "Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True).add_roles("Sales User")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def test_a_rep_cannot_read_the_settings(self):
		frappe.set_user(REP)
		self.assertFalse(frappe.has_permission("ERPNext CRM Settings", "read"))

	def test_a_rep_can_still_ask_whether_the_integration_is_on(self):
		frappe.db.set_single_value("ERPNext CRM Settings", "enabled", 1)
		frappe.set_user(REP)
		self.assertTrue(erp.is_enabled())

	def test_the_form_script_asks_the_narrow_endpoint_not_the_singleton(self):
		script = erp.get_crm_form_script()
		self.assertIn("erpnext_crm_settings.is_enabled", script)
		self.assertNotIn("frappe.client.get_single_value", script)


SETTINGS = "ERPNext CRM Settings"


class SiteUrlAndItsSecretTest(IntegrationTestCase):
	"""The API secret is masked on read but sent to whatever the site URL says, and a
	Sales Manager can write the site URL. The URL is checked when it changes, the
	stored secret does not follow it to another host, and what the other site
	answers is not relayed to the browser."""

	URL = "https://erp.example.com"

	def setUp(self):
		super().setUp()
		from frappe.utils.password import set_encrypted_password

		from crm.integrations import remote_url

		frappe.set_user("Administrator")
		# off: validate() then does nothing but judge the document
		_enable(enabled=0, create_customer_on_status_change=0, erpnext_site_url=self.URL, api_key="key")
		set_encrypted_password(SETTINGS, SETTINGS, "stored-api-secret", "api_secret")
		frappe.db.set_single_value(SETTINGS, "api_secret", "*" * 17)
		frappe.clear_document_cache(SETTINGS, SETTINGS)

		def resolve(host):
			return ["10.0.3.7"] if host.endswith(".internal") else ["93.184.215.14"]

		for patcher in (
			patch.object(remote_url, "_resolve", side_effect=resolve),
			patch.dict(frappe.local.conf, {"developer_mode": 0, remote_url.TRUSTED_HOSTS_CONFIG: []}),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		# as CustomerPushOffTheSavePathTest: off, even if something above committed
		frappe.db.set_single_value(SETTINGS, "enabled", 0)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		super().tearDown()

	def stored(self):
		return frappe.get_doc(SETTINGS).get_password("api_secret", raise_exception=False)

	def enabled_remote(self):
		"""The integration on, pointed at a private host, with only the remote call
		left of what an enabled save does: the rest alters tables (custom fields),
		which commits, and has nothing to do with where the secret may go."""
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		_enable(erpnext_site_url="http://erpnext-frontend.internal:8080", api_key="key")
		for method in (
			"add_quotation_to_option",
			"create_custom_fields_in_frappe_crm",
			"create_crm_form_script",
			"grant_item_access_to_sales_roles",
		):
			patcher = patch.object(erp.ERPNextCRMSettings, method)
			patcher.start()
			self.addCleanup(patcher.stop)
		settings = frappe.get_doc(SETTINGS)
		settings.erpnext_company = "Another Co"
		return settings

	def test_moving_the_site_does_not_take_the_stored_secret_with_it(self):
		for url in ("https://attacker.example", "https://erp.example.com:8443", "http://erp.example.com"):
			with self.subTest(url=url), self.assertRaises(frappe.ValidationError):
				frappe.client.set_value(SETTINGS, SETTINGS, {"erpnext_site_url": url})
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "erpnext_site_url"), self.URL)
		self.assertEqual(self.stored(), "stored-api-secret")

	def test_the_site_can_be_moved_by_entering_the_secret_again(self):
		frappe.client.set_value(
			SETTINGS, SETTINGS, {"erpnext_site_url": "https://erp2.example.com/", "api_secret": "new-secret"}
		)
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "erpnext_site_url"), "https://erp2.example.com")
		self.assertEqual(self.stored(), "new-secret")

	def test_removing_the_url_clears_the_secret_stored_for_it(self):
		frappe.client.set_value(SETTINGS, SETTINGS, {"erpnext_site_url": ""})
		self.assertIsNone(self.stored())

	def test_a_url_that_is_not_public_https_is_refused(self):
		for url in (
			"http://erp2.example.com",
			"https://127.0.0.1:8000",
			"http://erpnext.internal:8000",
			"https://key:secret@erp2.example.com",
		):
			with self.subTest(url=url), self.assertRaises(frappe.ValidationError):
				frappe.client.set_value(SETTINGS, SETTINGS, {"erpnext_site_url": url, "api_secret": "typed"})

	def test_a_private_site_the_operator_trusts_is_accepted(self):
		"""A self-hosted SIMERP on the same private network, on http: the site config
		names it, and then the pane can be pointed at it."""
		from crm.integrations import remote_url

		with patch.dict(frappe.local.conf, {remote_url.TRUSTED_HOSTS_CONFIG: ["erpnext.internal"]}):
			frappe.client.set_value(
				SETTINGS,
				SETTINGS,
				{"erpnext_site_url": "http://erpnext.internal:8000", "api_secret": "typed"},
			)
			erp.get_erpnext_site_client(frappe.get_doc(SETTINGS))  # and used
		self.assertEqual(self.stored(), "typed")

	def test_the_same_site_setup_has_no_url_to_judge(self):
		"""SIMERP installed on this very site: no URL, no key, nothing sent anywhere."""
		_enable(enabled=0, is_erpnext_in_different_site=0, erpnext_site_url="", api_key="")
		frappe.db.set_single_value(SETTINGS, "api_secret", "")
		settings = frappe.get_doc(SETTINGS)
		settings.erpnext_company = "Another Co"
		settings.save()
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "erpnext_company"), "Another Co")

	def test_a_stored_url_that_has_become_internal_is_not_sent_the_secret(self):
		frappe.db.set_single_value(SETTINGS, "erpnext_site_url", "https://moved.internal")
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		with patch.object(erp, "FrappeClient") as client, self.assertRaises(frappe.ValidationError):
			erp.get_erpnext_site_client(frappe.get_doc(SETTINGS))
		client.assert_not_called()

	def test_a_refused_host_is_explained_when_the_enabled_integration_is_saved(self):
		"""Enabled and remote, every save calls the other site. A host that is not
		allowed used to end that save with a bare exception -- "Failed to save
		settings" -- whichever field was being changed."""
		settings = self.enabled_remote()
		frappe.clear_messages()
		with (
			patch.object(erp, "FrappeClient") as client,
			self.assertRaises(frappe.ValidationError) as refused,
		):
			settings.save()
		client.assert_not_called()
		for text in (str(refused.exception), str(frappe.local.message_log)):
			self.assertIn("erpnext-frontend.internal", text)
			self.assertIn("crm_erp_trusted_hosts", text)

	def test_the_enabled_integration_saves_once_its_host_is_trusted(self):
		from crm.integrations import remote_url

		settings = self.enabled_remote()
		with (
			patch.dict(frappe.local.conf, {remote_url.TRUSTED_HOSTS_CONFIG: ["erpnext-frontend.internal"]}),
			patch.object(erp, "FrappeClient") as client,
		):
			settings.save()
		client.assert_called_once()
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "erpnext_company"), "Another Co")

	def test_the_client_does_not_follow_a_redirect(self):
		"""The site URL was checked; a 307 from it to the metadata address, or to a
		host of the sender's choosing with the key in the header, was not."""
		from unittest.mock import MagicMock

		import requests

		from crm.integrations.remote_url import RemoteHostNotAllowed

		answer = MagicMock(status_code=307, headers={"Location": "http://169.254.169.254/"})
		with patch.object(requests.Session, "request", return_value=answer) as request:
			client = erp.get_erpnext_site_client(frappe.get_doc(SETTINGS))
			with self.assertRaises(RemoteHostNotAllowed):
				client.get_list("Company", fields=["company_name"])
		self.assertIs(request.call_args.kwargs["allow_redirects"], False)
		self.assertEqual(request.call_args.kwargs["timeout"], (5, 30))

	def _redirecting_client(self):
		from unittest.mock import MagicMock

		from crm.integrations.remote_url import refuse_redirect

		def refused(*args, **kwargs):
			refuse_redirect(MagicMock(status_code=301), "SIMERP Site URL")

		client = MagicMock()
		client.post_api.side_effect = refused
		client.get_list.side_effect = refused
		return patch.object(erp, "get_erpnext_site_client", return_value=client)

	def test_a_redirecting_site_is_named_as_one_wherever_it_is_called(self):
		"""An http:// URL whose proxy answers 301 to https used to work by being
		followed. Refused, it has to say so: "check the Error Log" and "enable Data
		Synchronization" send an admin looking in the wrong place."""
		settings = self.enabled_remote()
		deal = _won_deal()
		calls = {
			"saving the settings": settings.save,
			"refreshing companies": settings.get_external_companies,
			"the customer link": lambda: erp.get_customer_link(deal.name),
			"creating a prospect": lambda: erp.create_prospect_in_remote_site(deal.name, settings),
		}
		for name, call in calls.items():
			frappe.clear_messages()
			with (
				self.subTest(call=name),
				self._redirecting_client(),
				patch.object(erp, "_check_user_rate_limit"),
				self.assertRaises(frappe.ValidationError) as refused,
			):
				call()
			self.assertIn("redirect", str(refused.exception))
			self.assertIn("redirect", str(frappe.local.message_log))

	def test_what_the_other_site_answers_is_not_relayed(self):
		"""Refresh companies raised whatever the remote said -- its traceback, or the
		first lines of any page an internal URL served."""
		settings = frappe.get_doc(SETTINGS)
		with patch.object(erp, "get_erpnext_site_client") as client:
			client.return_value.get_list.side_effect = Exception(
				"<html>internal admin page: token=abc</html>"
			)
			with self.assertRaises(frappe.ValidationError) as failed:
				settings.get_external_companies()
		self.assertNotIn("internal admin page", str(failed.exception))
		self.assertNotIn("token=abc", str(frappe.local.message_log))
