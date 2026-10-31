from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import importer, webhook


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
		# the same id the scheduler and the manual backfill use, so a burst of
		# notifications cannot stack sweeps on top of a running import
		self.assertEqual(enqueue.call_args.kwargs["job_id"], "acumatica_sync")
		# the first notification after switch-on sweeps from nothing, which is a full
		# backfill: it must not die at the long queue's 1500s default
		self.assertEqual(enqueue.call_args.kwargs["timeout"], importer.BACKFILL_TIMEOUT)
		self.assertGreater(importer.BACKFILL_TIMEOUT, 1500)

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_wrong_key_401s(self, enqueue):
		with self.assertRaises(frappe.PermissionError):
			self._call("wrong")
		enqueue.assert_not_called()

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_a_non_ascii_key_is_refused_not_a_server_error(self, enqueue):
		"""compare_digest raises TypeError on a str with non-ASCII characters: any guest
		could get a 500, and an Error Log row, per request."""
		for key in ("é", "tok123é"):
			with self.assertRaises(frappe.PermissionError):
				self._call(headers={"X-Vectora-Key": key})
		enqueue.assert_not_called()

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_missing_stored_token_401s_even_with_matching_empty(self, enqueue):
		_set_token("")
		frappe.clear_cache(doctype="CRM Acumatica Settings")
		with self.assertRaises(frappe.PermissionError):
			self._call("")
		enqueue.assert_not_called()

	@patch("crm.integrations.acumatica.importer.run_backfill")
	def test_a_sweep_a_webhook_woke_runs_as_the_system_not_as_guest(self, run_backfill):
		"""rq runs a job as the user who enqueued it, and the webhook enqueues from a
		guest request -- so every record the sweep wrote, and every deal it closed,
		was owned and modified by Guest."""
		seen = []
		run_backfill.side_effect = lambda **kw: seen.append(frappe.session.user)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Guest")  # what the job inherits from handle_notification

		importer.nightly_sweep()

		self.assertEqual(seen, ["Administrator"])

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_key_in_header_is_accepted(self, enqueue):
		# Note: the brief's test constructs a FakeRequest(args=..., headers=...) and
		# sets frappe.local.request directly. This file already fakes the request via
		# the _call() helper (a MagicMock patched onto frappe.local.request), so the
		# header is threaded through that helper instead of introducing a new fake.
		out = self._call(headers={"X-Vectora-Key": "tok123"})
		self.assertEqual(out, {"ok": True})
		enqueue.assert_called_once()
