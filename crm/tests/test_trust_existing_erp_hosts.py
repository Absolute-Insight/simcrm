"""The upgrade that introduces the ERP host check must not stop a working integration.

A site already pointed at ``http://erpnext-frontend:8080`` or a 192.168.x address
was configured by its operator and has been syncing; the request-time check would
refuse it on the first call after the upgrade. The patch lists such a host in
``crm_erp_trusted_hosts`` -- during migrate, which is an operator's action.
"""

import socket
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.integrations import remote_url
from crm.patches.v1_0 import trust_existing_internal_erp_hosts as trust

ACUMATICA = "CRM Acumatica Settings"
ERPNEXT = "ERPNext CRM Settings"

NAMES = {
	"erpnext-frontend": ["172.18.0.5"],
	"acumatica.lan": ["192.168.10.4"],
	"mbp.example.com": ["93.184.215.14"],
	"erp.example.com": ["93.184.215.14"],
}


def resolve(host):
	if host not in NAMES:
		raise socket.gaierror("no such host")
	return NAMES[host]


class TrustExistingErpHostsTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.written = []
		for patcher in (
			patch.object(remote_url, "_resolve", side_effect=resolve),
			patch.dict(frappe.local.conf, {remote_url.TRUSTED_HOSTS_KEY: []}),
			# never the real file: test_site's config is shared
			patch.object(trust, "update_site_config", side_effect=self._write),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _write(self, key, value, **kwargs):
		self.written.append((key, value))

	def _saved(self, acumatica="", erpnext=""):
		frappe.db.set_single_value(ACUMATICA, "instance_url", acumatica)
		frappe.db.set_single_value(ERPNEXT, "erpnext_site_url", erpnext)

	def test_an_internal_host_already_in_use_is_trusted_and_keeps_working(self):
		self._saved(acumatica="https://acumatica.lan/Live", erpnext="http://erpnext-frontend:8080")
		for url in ("https://acumatica.lan/Live", "http://erpnext-frontend:8080"):
			with self.assertRaises(remote_url.RemoteHostNotAllowed):
				remote_url.ensure_host_allowed(url, "URL")

		trust.execute()

		self.assertEqual(
			self.written, [(remote_url.TRUSTED_HOSTS_KEY, ["acumatica.lan", "erpnext-frontend"])]
		)
		# and the running process sees it without a restart
		remote_url.ensure_host_allowed("https://acumatica.lan/Live", "URL")
		remote_url.ensure_host_allowed("http://erpnext-frontend:8080", "URL")

	def test_an_address_and_a_name_that_does_not_resolve_are_trusted_too(self):
		"""Not resolving from the migrate container is no proof the workers cannot
		reach it; availability wins, and the log says what was trusted."""
		self._saved(acumatica="http://10.0.0.5:8081/acu", erpnext="https://erp.vpn-only.example")
		trust.execute()
		self.assertEqual(self.written, [(remote_url.TRUSTED_HOSTS_KEY, ["10.0.0.5", "erp.vpn-only.example"])])

	def test_a_public_host_is_not_added(self):
		self._saved(acumatica="https://mbp.example.com/MBP", erpnext="https://erp.example.com")
		trust.execute()
		self.assertEqual(self.written, [])
		self.assertEqual(remote_url.trusted_hosts(), set())

	def test_nothing_saved_is_nothing_to_do(self):
		self._saved()
		trust.execute()
		self.assertEqual(self.written, [])

	def test_what_the_operator_already_trusts_is_kept_and_not_repeated(self):
		self._saved(acumatica="https://acumatica.lan", erpnext="http://erpnext-frontend:8080")
		with patch.dict(
			frappe.local.conf, {remote_url.TRUSTED_HOSTS_KEY: ["Other.Internal", "erpnext-frontend"]}
		):
			trust.execute()
			self.assertEqual(
				self.written,
				[(remote_url.TRUSTED_HOSTS_KEY, ["Other.Internal", "erpnext-frontend", "acumatica.lan"])],
			)
			# again: everything is listed, so the file is not touched
			trust.execute()
			self.assertEqual(len(self.written), 1)

	def test_a_comma_separated_value_is_merged_as_a_list(self):
		self._saved(erpnext="http://erpnext-frontend:8080")
		with patch.dict(frappe.local.conf, {remote_url.TRUSTED_HOSTS_KEY: "a.internal, b.internal"}):
			trust.execute()
		self.assertEqual(
			self.written, [(remote_url.TRUSTED_HOSTS_KEY, ["a.internal", "b.internal", "erpnext-frontend"])]
		)

	def test_a_url_that_cannot_be_read_is_left_for_a_person(self):
		self._saved(acumatica="not a url", erpnext="ftp://files.internal")
		trust.execute()
		self.assertEqual(self.written, [])

	def test_what_it_trusted_is_logged(self):
		self._saved(erpnext="http://erpnext-frontend:8080")
		with patch.object(trust, "_log") as log:
			trust.execute()
		self.assertIn("erpnext-frontend", str(log.call_args))
		self.assertIn("SIMERP", str(log.call_args))
