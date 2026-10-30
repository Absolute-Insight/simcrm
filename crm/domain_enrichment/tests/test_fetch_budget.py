# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The wall-clock bound on ``http.fetch``.

``request_timeout`` is a per-socket-read timeout: ``requests`` restarts it on every
byte that arrives, so a host trickling one byte every few seconds never trips it and
holds the worker until gunicorn kills it. ``enrich_preview`` runs that fetch inside
the web request, rate-limited at 10 a minute against eight shipped workers, so a
handful of slow-drip hosts is enough to stall the app for everyone.

Offline: the fakes open no socket, and the real-socket cases below talk only to a
server on 127.0.0.1 (the SSRF guard is stubbed to let it through). The clock is
real but the budgets are fractions of a second.
"""

from __future__ import annotations

import socket
import threading
import time
from unittest import mock

from frappe.tests import UnitTestCase

from crm.domain_enrichment import extractors, http
from crm.domain_enrichment.result import CrawledPage
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


def _serve_once(respond):
	"""A one-connection server on 127.0.0.1; ``respond(conn)`` writes the reply.

	Returns the port. The server thread ends when ``respond`` does or the client
	hangs up -- a send into a socket the fetch shut down raises, and that is fine."""
	server = socket.socket()
	server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	server.bind(("127.0.0.1", 0))
	server.listen(1)

	def handle():
		try:
			conn, _addr = server.accept()
			conn.recv(65536)
			try:
				respond(conn)
			except OSError:
				pass
			finally:
				conn.close()
		finally:
			server.close()

	threading.Thread(target=handle, daemon=True).start()
	return server.getsockname()[1]


def _trickle(conn, payload: bytes, pause: float, seconds: float):
	ends = time.monotonic() + seconds
	while time.monotonic() < ends:
		time.sleep(pause)
		conn.sendall(payload)


class RealSocketBudgetTest(UnitTestCase):
	"""The bound must hold against a real socket, not just a fake that yields one byte
	at a time: ``iter_content`` blocks in ``recv()`` until a whole chunk arrives, and
	the status line and headers are read before any of fetch's own code runs."""

	BUDGET = 0.5
	TRICKLE = 4.0  # how long the server would keep going if nothing stopped it

	def _fetch(self, port):
		# request_timeout (per read) is far longer than the gap between bytes, so only
		# the budget can end this
		cfg = make_config({"request_timeout": 2, "retry_count": 0, "max_fetch_seconds": self.BUDGET})
		with mock.patch.object(http, "_validated_ips", return_value=["127.0.0.1"]):
			started = time.monotonic()
			result = http.fetch(f"http://trickle.example:{port}/", cfg)
		return time.monotonic() - started, result

	def test_a_trickled_body_ends_at_the_budget_and_keeps_what_arrived(self):
		first_chunk = b"<html>" + b"x" * (16_384 - len(b"<html>"))

		def respond(conn):
			conn.sendall(
				b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 100000\r\n\r\n" + first_chunk
			)
			_trickle(conn, b"x", 0.05, self.TRICKLE)

		elapsed, (status, html, error, _final) = self._fetch(_serve_once(respond))

		self.assertLess(elapsed, self.BUDGET + 1.0, f"a trickled body held fetch for {elapsed:.2f}s")
		self.assertEqual((status, error), (200, ""))
		self.assertTrue(html.startswith("<html>xxx"), "a chunk that arrived before the deadline is kept")

	def test_a_body_trickled_from_the_first_byte_reports_the_budget(self):
		def respond(conn):
			conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 100000\r\n\r\n")
			_trickle(conn, b"x", 0.05, self.TRICKLE)

		elapsed, (status, html, error, _final) = self._fetch(_serve_once(respond))

		self.assertLess(elapsed, self.BUDGET + 1.0, f"a trickled body held fetch for {elapsed:.2f}s")
		self.assertEqual((status, html), (0, ""))
		self.assertIn("fetch budget", error)

	def test_trickled_headers_end_at_the_budget(self):
		def respond(conn):
			conn.sendall(b"HTTP/1.1 200 OK\r\nX-Pad: ")
			_trickle(conn, b"a", 0.05, self.TRICKLE)

		elapsed, (status, html, error, _final) = self._fetch(_serve_once(respond))

		self.assertLess(elapsed, self.BUDGET + 1.0, f"trickled headers held fetch for {elapsed:.2f}s")
		self.assertEqual((status, html), (0, ""))
		self.assertIn("fetch budget", error)

	def test_a_prompt_answer_is_untouched(self):
		def respond(conn):
			body = b"<html><title>Acme</title></html>"
			conn.sendall(
				b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
				+ f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
				+ body
			)

		elapsed, (status, html, error, _final) = self._fetch(_serve_once(respond))

		self.assertEqual((status, error), (200, ""))
		self.assertIn("<title>Acme</title>", html)


def _serve_every(status: int, connections: int, extra_headers: str = ""):
	"""A server on 127.0.0.1 that answers each of ``connections`` requests with the same
	small HTML ``status`` page, one connection each. Returns ``(port, hits)``."""
	body = b"<html><title>Busy</title><body>Come back later.</body></html>"
	reply = (
		f"HTTP/1.1 {status} Busy\r\nContent-Type: text/html\r\n{extra_headers}"
		f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
	).encode() + body
	server = socket.socket()
	server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	server.bind(("127.0.0.1", 0))
	server.listen(connections)
	hits = []

	def handle():
		try:
			for _ in range(connections):
				conn, _addr = server.accept()
				try:
					conn.recv(65536)
					hits.append(time.monotonic())
					conn.sendall(reply)
				except OSError:
					pass
				finally:
					conn.close()
		except OSError:
			pass
		finally:
			server.close()

	threading.Thread(target=handle, daemon=True).start()
	return server.getsockname()[1], hits


class RetryPolicyTest(UnitTestCase):
	"""Retries happen inside ``adapter.send``, below every check ``fetch`` makes, and no
	socket is open while urllib3 sleeps between them -- so no deadline on a socket can
	cut a sleep short. The policy itself has to keep its sleeps inside the budget."""

	def _fetch(self, port, retries=2, budget=1.0):
		cfg = make_config({"request_timeout": 2, "retry_count": retries, "max_fetch_seconds": budget})
		with mock.patch.object(http, "_validated_ips", return_value=["127.0.0.1"]):
			started = time.monotonic()
			result = http.fetch(f"http://busy.example:{port}/", cfg)
		return time.monotonic() - started, result

	def test_a_retry_after_header_does_not_hold_the_fetch(self):
		"""WordPress maintenance mode answers 503 with ``Retry-After: 600``. Honoured, two
		retries held the preview's web worker for twenty minutes (urllib3 caps the wait
		at six hours, not at anything of ours)."""
		port, _hits = _serve_every(503, 3, "Retry-After: 3\r\n")

		elapsed, (status, _html, _error, _final) = self._fetch(port)

		self.assertLess(elapsed, 2.0, f"Retry-After held a 1s fetch for {elapsed:.2f}s")
		self.assertEqual(status, 503)

	def test_backoff_never_sleeps_past_the_budget(self):
		"""Exponential backoff with a generous retry_count adds up to minutes."""
		port, _hits = _serve_every(500, 12)

		elapsed, (_status, _html, _error, _final) = self._fetch(port, retries=10)

		self.assertLess(elapsed, 2.0, f"backoff held a 1s fetch for {elapsed:.2f}s")

	def test_a_persistent_429_comes_back_as_a_429(self):
		"""A site that answers 429 to everything is a bot wall, and its status is the only
		thing that says so. Raised as a RetryError once the retries ran out, it came
		back as status 0 and was diagnosed "Couldn't reach this website"."""
		port, hits = _serve_every(429, 3)

		_elapsed, (status, html, error, final) = self._fetch(port, budget=5)

		self.assertEqual(len(hits), 3, "a 429 is still retried")
		self.assertEqual((status, error), (429, ""))
		page = CrawledPage(url=final, status_code=status, html=html, error=error)
		self.assertEqual(extractors.diagnose_readability([page]), "blocked")
