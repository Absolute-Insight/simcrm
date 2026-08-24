from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import webhook


class TestWebhook(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "webhook_verify_token", "tok123")
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def tearDown(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def _call(self, key):
		req = MagicMock()
		req.args = {"key": key} if key is not None else {}
		with patch.object(frappe.local, "request", req, create=True):
			return webhook.handle_notification()

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_valid_key_enqueues_sweep(self, enqueue):
		out = self._call("tok123")
		self.assertTrue(out["ok"])
		self.assertEqual(enqueue.call_args[0][0], "crm.integrations.acumatica.importer.nightly_sweep")

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_wrong_key_401s(self, enqueue):
		with self.assertRaises(frappe.PermissionError):
			self._call("wrong")
		enqueue.assert_not_called()

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_missing_stored_token_401s_even_with_matching_empty(self, enqueue):
		frappe.db.set_single_value("CRM Acumatica Settings", "webhook_verify_token", "")
		frappe.clear_cache(doctype="CRM Acumatica Settings")
		with self.assertRaises(frappe.PermissionError):
			self._call("")
		enqueue.assert_not_called()
