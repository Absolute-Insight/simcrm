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
		"""Child rows autoincrement, so ``issue.name`` is an int here and arrives from
		the browser as a string: the comparison never matched and no product sync
		issue could ever be cleared."""
		issue = self._append_issue()

		self.assertTrue(erp.dismiss_sync_issue(str(issue.name)))

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
