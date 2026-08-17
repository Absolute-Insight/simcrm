# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The public URL Twilio is told to call back on.

It was ``get_url().split(":8", 1)[0] + path``, which strips from the first
``:8`` onwards -- so it ate *any* port beginning with 8. A site on ``:8443``,
the conventional alternative HTTPS port and a perfectly public one, handed
Twilio a URL with no port at all and every callback went somewhere else. There
was no error: Twilio simply called a host that did not answer on 443, and the
recording or status update never arrived.

Nothing here needs a Twilio account. ``get_url`` is patched, so what is asserted
is the URL arithmetic, which is the part that was wrong.
"""

from __future__ import annotations

from unittest import mock

from frappe.tests import UnitTestCase

from crm.integrations.twilio import utils


def public_url(site_url: str, path: str | None = "/api/x"):
	with mock.patch.object(utils, "get_url", return_value=site_url):
		return utils.get_public_url(path)


class PublicUrlTest(UnitTestCase):
	def test_a_bench_port_is_dropped(self):
		"""The behaviour worth keeping: a callback to :8000 is unreachable from
		the public internet, so the proxy's address is what Twilio needs."""
		self.assertEqual(public_url("http://site.test:8000"), "http://site.test/api/x")

	def test_the_other_bench_ports_are_dropped_too(self):
		self.assertEqual(public_url("http://site.test:8080"), "http://site.test/api/x")
		self.assertEqual(public_url("http://site.test:9000"), "http://site.test/api/x")

	def test_a_real_port_is_kept(self):
		"""The bug. 8443 begins with 8 and was eaten by the substring split."""
		self.assertEqual(public_url("https://site.test:8443"), "https://site.test:8443/api/x")

	def test_another_non_bench_port_is_kept(self):
		self.assertEqual(public_url("https://site.test:8888"), "https://site.test:8888/api/x")

	def test_a_url_with_no_port_is_unchanged(self):
		self.assertEqual(public_url("https://crm.example.com"), "https://crm.example.com/api/x")

	def test_a_hostname_containing_eight_is_not_mangled(self):
		"""The substring split only matched ``:8``, so this was already safe --
		asserted so a future 'simplification' back to string surgery fails."""
		self.assertEqual(public_url("https://site8.example.com"), "https://site8.example.com/api/x")

	def test_a_trailing_slash_does_not_double_up(self):
		self.assertEqual(public_url("https://site.test/"), "https://site.test/api/x")

	def test_no_path_returns_the_base_url_rather_than_raising(self):
		"""``str + None``. The signature has defaulted to None since this was
		written, so calling it the way the type hint invites was a TypeError."""
		self.assertEqual(public_url("https://site.test:8443", None), "https://site.test:8443")

	def test_the_settings_module_reexports_the_same_function(self):
		"""It used to hold a byte-identical copy, so the bug had to be found and
		fixed twice. One definition now."""
		from crm.fcrm.doctype.crm_twilio_settings.crm_twilio_settings import (
			get_public_url as settings_url,
		)

		with mock.patch.object(utils, "get_url", return_value="https://site.test:8443"):
			self.assertEqual(settings_url("/api/x"), "https://site.test:8443/api/x")
