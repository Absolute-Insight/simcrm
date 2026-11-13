"""Where the ERP integrations may send their stored credentials.

The settings documents hold a URL and the secrets posted to it, and a Sales Manager
can write both. These pin the rules for the URL itself; what the two controllers do
with them is in their own test modules.
"""

import socket
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.integrations import remote_url
from crm.integrations.remote_url import (
	RemoteHostNotAllowed,
	ensure_host_allowed,
	host_changed,
	validate_remote_url,
)

PUBLIC = "93.184.215.14"


def resolving(mapping: dict):
	"""DNS for the test: names in ``mapping`` resolve to it, everything else fails."""

	def resolve(host):
		if host not in mapping:
			raise socket.gaierror("no such host")
		return [mapping[host]] if isinstance(mapping[host], str) else list(mapping[host])

	return patch.object(remote_url, "_resolve", side_effect=resolve)


def site(developer_mode=False, trusted=None):
	conf = {"developer_mode": 1 if developer_mode else 0, remote_url.TRUSTED_HOSTS_CONFIG: trusted or []}
	return patch.dict(frappe.local.conf, conf)


class TestRemoteURL(IntegrationTestCase):
	def test_a_public_https_url_is_stored_without_its_trailing_slash(self):
		with site(), resolving({"mbp.example.com": PUBLIC}):
			self.assertEqual(
				validate_remote_url(" https://mbp.example.com/MBP/ ", "Instance URL"),
				"https://mbp.example.com/MBP",
			)
			self.assertEqual(validate_remote_url("", "Instance URL"), "")

	def test_http_is_refused_outside_developer_mode(self):
		with resolving({"erp.example.com": PUBLIC}):
			with site(), self.assertRaises(frappe.ValidationError):
				validate_remote_url("http://erp.example.com", "Site URL")
			with site(developer_mode=True):
				self.assertEqual(
					validate_remote_url("http://erp.example.com", "Site URL"), "http://erp.example.com"
				)

	def test_what_is_not_an_http_url_is_refused(self):
		with site(developer_mode=True), resolving({"erp.example.com": PUBLIC}):
			for url in (
				"erp.example.com",
				"ftp://erp.example.com",
				"file:///etc/passwd",
				"gopher://erp.example.com",
				"https://",
				"https://erp.example.com:port",
				"https://erp.example.com\\@attacker.example",
				"https://erp.example.com\n.attacker.example",
			):
				with self.subTest(url=url), self.assertRaises(frappe.ValidationError):
					validate_remote_url(url, "Site URL")

	def test_a_host_that_is_not_a_hostname_is_not_a_url(self):
		"""urlparse hands back whatever sat between // and /: quotes, semicolons. The
		host ends up in a log line and a command an operator is told to run."""
		with site(developer_mode=True), resolving({}):
			for url in (
				"http://x';id;'.example",
				"https://erp.example.com$(id)",
				"https://erp.example.com`id`",
				'https://erp"example.com',
				"https://erp.example.com;id",
				"https://erp.example.com|id",
				"https://ерп.example",
			):
				with self.subTest(url=url):
					self.assertIsNone(remote_url.origin(url))
					with self.assertRaises(frappe.ValidationError):
						validate_remote_url(url, "Site URL")
			# what a hostname is made of still passes
			for url in (
				"https://erp-1.example.com",
				"http://erpnext_frontend:8080",
				"https://[fd00::1]",
				"https://10.0.0.5",
			):
				self.assertIsNotNone(remote_url.origin(url), url)

	def test_credentials_in_the_url_are_refused(self):
		with site(), resolving({"erp.example.com": PUBLIC}):
			for url in ("https://user:pw@erp.example.com", "https://user@erp.example.com"):
				with self.subTest(url=url), self.assertRaises(frappe.ValidationError):
					validate_remote_url(url, "Site URL")

	def test_an_internal_target_is_refused(self):
		"""Typed as an address, typed as a name for one, or spelt so a naive check
		would not see it: the stored secrets are not posted into the server's own
		network, and Test connection is not a port scanner for it."""
		names = {
			"db.internal": "10.0.3.7",
			"metadata.example": "169.254.169.254",
			"both.example": [PUBLIC, "192.168.1.10"],
			"v6.example": "fd00::1",
			"2130706433": "127.0.0.1",
		}
		with site(developer_mode=True), resolving(names):
			for url in (
				"https://127.0.0.1",
				"https://127.0.0.1:8000/api",
				"https://localhost",
				"https://LOCALHOST.",
				"https://app.localhost",
				"https://10.0.0.5",
				"https://192.168.1.1",
				"https://172.16.4.4",
				"https://169.254.169.254/latest/meta-data",
				"https://100.64.0.1",
				"https://0.0.0.0",
				"https://[::1]",
				"https://[fe80::1]",
				"https://[::ffff:10.0.0.1]",
				"https://db.internal",
				"https://metadata.example",
				"https://both.example",
				"https://v6.example",
				"https://2130706433",
				"http://redis-cache:6379",
			):
				names.setdefault("redis-cache", "172.18.0.3")
				with self.subTest(url=url), self.assertRaises(RemoteHostNotAllowed):
					validate_remote_url(url, "Site URL")

	def test_the_refusal_does_not_say_what_the_name_resolved_to(self):
		with site(), resolving({"db.internal": "10.0.3.7"}):
			with self.assertRaises(RemoteHostNotAllowed) as refused:
				validate_remote_url("https://db.internal", "Site URL")
		self.assertNotIn("10.0.3.7", str(refused.exception))
		self.assertIn(remote_url.TRUSTED_HOSTS_CONFIG, str(refused.exception))

	def test_a_host_the_operator_trusts_may_be_private_and_plain_http(self):
		"""A self-hosted ERPNext sits on a private address, usually on http inside a
		compose network. The site config says so; no application role can."""
		with site(trusted=["erpnext.internal", "10.0.0.9"]), resolving({"erpnext.internal": "10.0.3.7"}):
			self.assertEqual(
				validate_remote_url("http://ERPNext.internal:8000", "Site URL"),
				"http://ERPNext.internal:8000",
			)
			self.assertEqual(validate_remote_url("https://10.0.0.9", "Site URL"), "https://10.0.0.9")
			ensure_host_allowed("http://erpnext.internal:8000", "Site URL")
			# trusted by exact host: neither a neighbour nor a subdomain of it
			for url in ("https://10.0.0.10", "https://x.erpnext.internal"):
				with self.subTest(url=url), self.assertRaises(frappe.ValidationError):
					with resolving({"x.erpnext.internal": "10.0.3.8"}):
						validate_remote_url(url, "Site URL")
		with site(trusted="erpnext.internal, other.internal"), resolving({"other.internal": "10.0.3.9"}):
			self.assertTrue(validate_remote_url("http://other.internal", "Site URL"))

	def test_a_name_that_does_not_resolve_yet_can_be_saved_but_not_used_once_it_is_internal(self):
		with site(), resolving({}):
			self.assertEqual(
				validate_remote_url("https://soon.example.com", "Site URL"), "https://soon.example.com"
			)
			ensure_host_allowed("https://soon.example.com", "Site URL")
		# what it resolves to when the request is made is what counts
		with site(), resolving({"soon.example.com": "10.0.3.7"}):
			with self.assertRaises(RemoteHostNotAllowed):
				ensure_host_allowed("https://soon.example.com", "Site URL")
		with site(), resolving({"soon.example.com": PUBLIC}):
			ensure_host_allowed("https://soon.example.com", "Site URL")

	def test_a_stored_url_is_checked_again_when_a_request_is_made(self):
		with site(), resolving({}):
			for url in ("https://127.0.0.1", "http://10.0.0.5:8000", "https://localhost", "", "not a url"):
				with self.subTest(url=url), self.assertRaises(RemoteHostNotAllowed):
					ensure_host_allowed(url, "Site URL")

	def test_the_http_refusal_says_what_would_be_accepted(self):
		with site(), resolving({"erp.example.com": PUBLIC}):
			with self.assertRaises(frappe.ValidationError) as refused:
				validate_remote_url("http://erp.example.com", "Site URL")
		self.assertIn("https://", str(refused.exception))
		self.assertIn(remote_url.TRUSTED_HOSTS_CONFIG, str(refused.exception))

	def test_the_refusal_names_the_host_and_the_key_for_whoever_has_to_act(self):
		with site(), resolving({"erpnext-frontend": "172.18.0.5"}):
			with self.assertRaises(RemoteHostNotAllowed) as refused:
				ensure_host_allowed("http://erpnext-frontend:8080", "Site URL")
		self.assertIn("erpnext-frontend", str(refused.exception))
		self.assertIn(remote_url.TRUSTED_HOSTS_CONFIG, str(refused.exception))
		self.assertNotIn("172.18.0.5", str(refused.exception))

	def test_a_name_the_resolver_cannot_even_encode_is_not_allowed(self):
		"""An IDN error is not "does not resolve yet": nothing says the connection,
		which encodes the name its own way, would fail the same."""
		with site(), patch.object(remote_url, "_resolve", side_effect=UnicodeError("label too long")):
			self.assertEqual(remote_url.host_state("x" * 70 + ".example"), "invalid")
			with self.assertRaises(RemoteHostNotAllowed):
				validate_remote_url("https://" + "x" * 70 + ".example", "Site URL")
			with self.assertRaises(RemoteHostNotAllowed):
				ensure_host_allowed("https://" + "x" * 70 + ".example", "Site URL")

	def test_a_redirect_is_refused_rather_than_followed(self):
		"""The host was checked; where it sends the request next was not."""
		from unittest.mock import MagicMock

		remote_url.refuse_redirect(MagicMock(status_code=200), "Site URL")
		for status in (301, 302, 303, 307, 308):
			with self.subTest(status=status), self.assertRaises(RemoteHostNotAllowed) as refused:
				remote_url.refuse_redirect(MagicMock(status_code=status), "Site URL")
			self.assertIn("redirect", str(refused.exception))

	def test_what_counts_as_another_host(self):
		same = (
			("https://erp.example.com", "https://erp.example.com/"),
			("https://erp.example.com/MBP", "https://erp.example.com/Other"),
			("https://erp.example.com", "https://ERP.example.com:443"),
			("http://erp.example.com", "http://erp.example.com:80/x"),
			("", None),
			(" ", ""),
		)
		other = (
			("https://erp.example.com", "https://attacker.example"),
			("https://erp.example.com", "https://erp.example.com.attacker.example"),
			("https://erp.example.com", "http://erp.example.com"),
			("https://erp.example.com", "https://erp.example.com:8443"),
			("https://erp.example.com", ""),
			("", "https://erp.example.com"),
			(None, "https://erp.example.com"),
			("not a url", "also not one"),
		)
		for old, new in same:
			self.assertFalse(host_changed(old, new), (old, new))
		for old, new in other:
			self.assertTrue(host_changed(old, new), (old, new))
