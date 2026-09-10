# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The wall-clock bound on ``http.fetch``.

``request_timeout`` is a per-socket-read timeout: ``requests`` restarts it on every
byte that arrives, so a host trickling one byte every few seconds never trips it and
holds the worker until gunicorn kills it. ``enrich_preview`` runs that fetch inside
the web request, rate-limited at 10 a minute against eight shipped workers, so a
handful of slow-drip hosts is enough to stall the app for everyone.

Fully offline: no socket is opened, the responses are fakes and the clock is real but
the budgets are milliseconds.
"""

from __future__ import annotations

import time
from unittest import mock

from frappe.tests import UnitTestCase

from crm.domain_enrichment import http
from crm.domain_enrichment.tests.fixtures import make_config


class FakeResponse:
	def __init__(self, chunks, headers=None, status_code=200, is_redirect=False):
		self._chunks = chunks
		self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
		self.encoding = "utf-8"
		self.status_code = status_code
		self.is_redirect = is_redirect
		self.is_permanent_redirect = False
		self.closed = False

	def iter_content(self, chunk_size=None, decode_unicode=False):
		yield from self._chunks

	def close(self):
		self.closed = True


def _dribble(payload=b"", pause=0.01):
	"""A host that stays technically alive forever without ever finishing."""
	while True:
		time.sleep(pause)
		yield payload


class ReadCappedDeadlineTest(UnitTestCase):
	def test_a_trickle_ends_at_the_deadline_instead_of_running_forever(self):
		resp = FakeResponse(_dribble(b"x"))
		started = time.monotonic()

		html = http._read_capped(resp, 10_000_000, time.monotonic() + 0.05)

		self.assertLess(time.monotonic() - started, 5, "the deadline must end the read")
		self.assertLess(len(html), 10_000_000)

	def test_keep_alive_dribble_with_no_payload_still_ends(self):
		"""Empty chunks never move the byte counter, so only the clock can stop this."""
		resp = FakeResponse(_dribble(b""))
		started = time.monotonic()

		html = http._read_capped(resp, 10_000_000, time.monotonic() + 0.05)

		self.assertLess(time.monotonic() - started, 5)
		self.assertEqual(html, "")

	def test_the_byte_cap_still_applies_on_its_own(self):
		resp = FakeResponse(iter([b"a" * 100, b"b" * 100]))

		html = http._read_capped(resp, 150)

		self.assertEqual(len(html), 200)  # stops after the chunk that crossed the cap

	def test_a_body_that_finishes_inside_the_budget_is_returned_whole(self):
		resp = FakeResponse(iter([b"<html>hi</html>"]))

		html = http._read_capped(resp, 10_000, time.monotonic() + 5)

		self.assertEqual(html, "<html>hi</html>")


class FetchBudgetTest(UnitTestCase):
	def test_the_budget_scales_with_the_configured_read_timeout(self):
		"""The preview path lowers request_timeout; its budget must follow it down."""
		cfg = make_config({"request_timeout": 8})
		self.assertEqual(http._fetch_budget(cfg, 8), 24.0)

	def test_the_budget_is_capped_however_long_the_read_timeout_is(self):
		cfg = make_config({"request_timeout": 600})
		self.assertEqual(http._fetch_budget(cfg, 600), float(http.MAX_FETCH_SECONDS))

	def test_an_explicit_setting_overrides_the_derived_budget(self):
		cfg = make_config({"request_timeout": 10, "max_fetch_seconds": 4})
		self.assertEqual(http._fetch_budget(cfg, 10), 4.0)

	def test_a_missing_config_still_has_a_budget(self):
		self.assertGreater(http._fetch_budget(None, 10), 0)


class FetchDeadlineTest(UnitTestCase):
	def test_a_redirect_chain_of_slow_hops_gives_up_on_the_budget(self):
		"""Each hop can sit inside its own read timeout and the chain still spends the
		worker's afternoon, so the deadline is re-checked before every hop."""
		cfg = make_config({"request_timeout": 5, "max_fetch_seconds": 0.05})
		hops = []

		def slow_redirect(session, url, ip, timeout, retries):
			hops.append(url)
			time.sleep(0.06)
			return FakeResponse(
				iter([]), headers={"Location": "https://slow.example/next"}, status_code=302, is_redirect=True
			)

		with (
			mock.patch.object(http, "_validated_ips", return_value=["93.184.216.34"]),
			mock.patch.object(http, "_pinned_get", side_effect=slow_redirect),
			mock.patch.object(http, "build_session", return_value=mock.MagicMock()),
		):
			status, html, error, final = http.fetch("https://slow.example/", cfg)

		self.assertEqual(status, 0)
		self.assertEqual(html, "")
		self.assertIn("fetch budget", error)
		self.assertEqual(len(hops), 1, "the second hop must not be attempted")

	def test_the_deadline_reaches_the_body_read(self):
		cfg = make_config({"request_timeout": 5, "max_fetch_seconds": 0.05})

		def dribbling_page(session, url, ip, timeout, retries):
			return FakeResponse(_dribble(b"x"))

		with (
			mock.patch.object(http, "_validated_ips", return_value=["93.184.216.34"]),
			mock.patch.object(http, "_pinned_get", side_effect=dribbling_page),
			mock.patch.object(http, "build_session", return_value=mock.MagicMock()),
		):
			started = time.monotonic()
			status, html, error, final = http.fetch("https://slow.example/", cfg)

		self.assertLess(time.monotonic() - started, 5)
		self.assertEqual(status, 200)
		self.assertEqual(error, "")

	def test_no_hop_may_outlast_the_remaining_budget(self):
		cfg = make_config({"request_timeout": 30, "max_fetch_seconds": 2})
		seen = []

		def record_timeout(session, url, ip, timeout, retries):
			seen.append(timeout)
			return FakeResponse(iter([b"<html></html>"]))

		with (
			mock.patch.object(http, "_validated_ips", return_value=["93.184.216.34"]),
			mock.patch.object(http, "_pinned_get", side_effect=record_timeout),
			mock.patch.object(http, "build_session", return_value=mock.MagicMock()),
		):
			http.fetch("https://slow.example/", cfg)

		self.assertLessEqual(seen[0], 2)
