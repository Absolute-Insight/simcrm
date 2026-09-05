from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import webhook


def _set_token(value):
	s = frappe.get_doc("CRM Acumatica Settings")
	s.webhook_verify_token = value
	s.flags.ignore_validate = True
	s.save(ignore_permissions=True)


class TestWebhook(FrappeTestCase):
	def setUp(self):
		_set_token("tok123")
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def tearDown(self):
		# one test blanks the token; leaving it blank would disarm the next one
		_set_token("")
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def _call(self, key=None, headers=None):
		req = MagicMock()
		req.args = {"key": key} if key is not None else {}
		req.headers = headers or {}
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
		_set_token("")
		frappe.clear_cache(doctype="CRM Acumatica Settings")
		with self.assertRaises(frappe.PermissionError):
			self._call("")
		enqueue.assert_not_called()

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_key_in_header_is_accepted(self, enqueue):
		# Note: the brief's test constructs a FakeRequest(args=..., headers=...) and
		# sets frappe.local.request directly. This file already fakes the request via
		# the _call() helper (a MagicMock patched onto frappe.local.request), so the
		# header is threaded through that helper instead of introducing a new fake.
		out = self._call(headers={"X-Vectora-Key": "tok123"})
		self.assertEqual(out, {"ok": True})
		enqueue.assert_called_once()
