"""The upgrade that introduces the ERP host check must not stop a working integration.

A site already pointed at ``http://erpnext-frontend:8080`` or a 192.168.x address
was configured by its operator and has been syncing; the request-time check would
refuse it on the first call after the upgrade. The patch lists such a host in
``crm_erp_trusted_hosts`` -- during migrate, which is an operator's action -- and
is careful about what it will not vouch for.

Nothing here touches the site config file or the network: the write and the
resolver are both replaced.
"""

import socket
import time
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.integrations import remote_url
from crm.patches.v1_0 import trust_existing_internal_erp_hosts as trust

ACUMATICA = "CRM Acumatica Settings"
ERPNEXT = "ERPNext CRM Settings"
CONFIG = remote_url.TRUSTED_HOSTS_CONFIG

NAMES = {
	"erpnext-frontend": ["172.18.0.5"],
	"acumatica.lan": ["192.168.10.4"],
	"ula.example": ["fd12:3456::9"],
	"mbp.example.com": ["93.184.215.14"],
	"erp.example.com": ["93.184.215.14"],
	"metadata.example": ["169.254.169.254"],
	"loop.example": ["127.0.0.1"],
	"mixed.example": ["10.0.0.9", "169.254.1.1"],
}


def resolve(host):
	if host not in NAMES:
		raise socket.gaierror("no such host")
	return NAMES[host]


class TrustExistingErpHostsTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.written = []
		self.logged = []
		for patcher in (
			patch.object(remote_url, "_resolve", side_effect=resolve),
			patch.dict(frappe.local.conf, {CONFIG: []}),
			# never the real file: test_site's config is shared
			patch.object(trust, "update_site_config", side_effect=self._write),
			patch.object(trust, "_log", side_effect=self.logged.append),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _write(self, name, value, **kwargs):
		self.written.append((name, value))

	def _saved(self, acumatica="", erpnext=""):
		frappe.db.set_single_value(ACUMATICA, "instance_url", acumatica)
		frappe.db.set_single_value(ERPNEXT, "erpnext_site_url", erpnext)

	def _trusted_after(self, acumatica="", erpnext=""):
		"""What one run on a site with nothing listed yet writes to the config."""
		frappe.local.conf[CONFIG] = []
		self.written.clear()
		self._saved(acumatica, erpnext)
		trust.execute()
		return self.written[-1][1] if self.written else []

	def test_an_internal_host_already_in_use_is_trusted_and_keeps_working(self):
		self._saved(acumatica="https://acumatica.lan/Live", erpnext="http://erpnext-frontend:8080")
		for url in ("https://acumatica.lan/Live", "http://erpnext-frontend:8080"):
			with self.assertRaises(remote_url.RemoteHostNotAllowed):
				remote_url.ensure_host_allowed(url, "URL")

		trust.execute()

		self.assertEqual(self.written, [(CONFIG, ["acumatica.lan", "erpnext-frontend"])])
		# and the running process sees it without a restart
		remote_url.ensure_host_allowed("https://acumatica.lan/Live", "URL")
		remote_url.ensure_host_allowed("http://erpnext-frontend:8080", "URL")

	def test_private_addresses_are_trusted(self):
		self.assertEqual(
			self._trusted_after(acumatica="http://10.0.0.5:8081/acu", erpnext="https://ula.example"),
			["10.0.0.5", "ula.example"],
		)

	def test_a_metadata_or_loopback_address_is_never_trusted_for_the_operator(self):
		"""169.254.169.254 is where a cloud hands out its credentials, and loopback is
		the server itself. If a saved URL really points there the operator can say so;
		an upgrade does not say it for them."""
		for url in (
			"http://169.254.169.254/latest",
			"https://[fe80::1]",
			"https://127.0.0.1:8443",
			"http://localhost:8000",
			"http://app.localhost",
			"https://[::1]",
			"https://metadata.example",
			"https://loop.example",
			# one private answer does not vouch for the link-local one beside it
			"https://mixed.example",
		):
			with self.subTest(url=url):
				self.logged.clear()
				self.assertEqual(self._trusted_after(erpnext=url), [])
				self.assertIn("NOT trusted", "\n".join(self.logged))
				self.assertIn("set-config", "\n".join(self.logged))

	def test_a_name_that_does_not_resolve_is_trusted_only_when_it_looks_internal(self):
		"""A compose service name or a .internal name that the migrate container
		cannot resolve is still plainly somebody's private host. A public-looking
		name whose DNS failed for a minute is not trusted for good because of it."""
		for host in ("erpnext-app", "erp.corp.internal", "erp.local", "nas.lan", "erp.test"):
			with self.subTest(host=host):
				self.assertEqual(self._trusted_after(erpnext=f"http://{host}:8000"), [host])
		for host in ("erp.vpn-only.example", "erp.customer.co.za"):
			with self.subTest(host=host):
				self.logged.clear()
				self.assertEqual(self._trusted_after(erpnext=f"https://{host}"), [])
				self.assertIn("NOT trusted", "\n".join(self.logged))
				# the line to run, whole
				self.assertIn(f"set-config -p {CONFIG} '[\"{host}\"]'", "\n".join(self.logged))

	def test_a_resolver_that_never_answers_does_not_stall_the_migrate(self):
		def hang(host):
			time.sleep(5)
			return ["93.184.215.14"]

		self._saved(acumatica="https://slow.example.com", erpnext="http://erpnext-app:8000")
		started = time.monotonic()
		with patch.object(remote_url, "_resolve", side_effect=hang), patch.object(trust, "DNS_TIMEOUT", 0.2):
			trust.execute()
		self.assertLess(time.monotonic() - started, 3)
		# treated as not resolving: the service name is trusted, the public-looking one is not
		self.assertEqual(self.written, [(CONFIG, ["erpnext-app"])])

	def test_a_site_config_that_cannot_be_written_does_not_abort_the_migrate(self):
		self._saved(erpnext="http://erpnext-frontend:8080")
		with patch.object(trust, "update_site_config", side_effect=PermissionError("read-only file system")):
			trust.execute()  # must not raise
		self.assertIn(f"set-config -p {CONFIG} '[\"erpnext-frontend\"]'", "\n".join(self.logged))
		self.assertNotIn("erpnext-frontend", remote_url.trusted_hosts())

	def test_a_public_host_is_not_added(self):
		self.assertEqual(
			self._trusted_after(acumatica="https://mbp.example.com/MBP", erpnext="https://erp.example.com"),
			[],
		)
		self.assertEqual(remote_url.trusted_hosts(), set())

	def test_nothing_saved_is_nothing_to_do(self):
		self.assertEqual(self._trusted_after(), [])
		self.assertEqual(self.logged, [])

	def test_what_the_operator_already_trusts_is_kept_and_not_repeated(self):
		self._saved(acumatica="https://acumatica.lan", erpnext="http://erpnext-frontend:8080")
		with patch.dict(frappe.local.conf, {CONFIG: ["Other.Internal", "erpnext-frontend"]}):
			trust.execute()
			self.assertEqual(
				self.written, [(CONFIG, ["Other.Internal", "erpnext-frontend", "acumatica.lan"])]
			)
			# again: everything is listed, so the file is not touched
			trust.execute()
			self.assertEqual(len(self.written), 1)

	def test_a_comma_separated_value_is_merged_as_a_list(self):
		self._saved(erpnext="http://erpnext-frontend:8080")
		with patch.dict(frappe.local.conf, {CONFIG: "a.internal, b.internal"}):
			trust.execute()
		self.assertEqual(self.written, [(CONFIG, ["a.internal", "b.internal", "erpnext-frontend"])])

	def test_a_url_that_cannot_be_read_is_left_for_a_person(self):
		self.assertEqual(self._trusted_after(acumatica="not a url", erpnext="ftp://files.internal"), [])

	def test_what_it_trusted_is_logged(self):
		self._trusted_after(erpnext="http://erpnext-frontend:8080")
		self.assertIn("erpnext-frontend", "\n".join(self.logged))
		self.assertIn("SIMERP", "\n".join(self.logged))
