# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""HTTP fetch layer for the crawler, built on framework helpers, with an SSRF guard.

Built on ``frappe.utils.get_request_session`` (so retry/adapter behavior is the
framework's), this module adds the crawler-specific behavior the framework does NOT
provide:

* a hard download cap (``max_download_bytes``) via streamed reads,
* an HTML-only content-type filter,
* the never-raise ``(status_code, html, error)`` contract, and
* a mandatory **SSRF guard** that resolves the hostname and rejects loopback /
  private / link-local / reserved addresses, honors the Settings allow/block lists,
  and **re-validates the resolved IP after every redirect** (it does not blindly
  follow redirects). Every connection is **pinned to the IP the guard validated**
  (Host header and TLS SNI/verification stay on the original hostname), so a
  DNS-rebinding host cannot pass validation with one address and connect to another.

Limits (timeout, byte cap, retries, user-agent) come from config, not constants.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import threading
import time
from urllib.parse import urlparse

import frappe
from frappe.utils import get_request_session
from requests.adapters import HTTPAdapter, Retry
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

HTML_CONTENT_TYPES = ("text/html", "application/xhtml")
RETRY_STATUS_FORCELIST = (429, 500, 502, 503, 504)
# Cap redirect chases ourselves (we follow manually to re-check each hop).
MAX_REDIRECTS = 5
# Total wall-clock seconds one fetch() may spend, redirects and body read included.
# `request_timeout` is per socket read and restarts on every byte, so it bounds
# nothing against a host that trickles; this does, at the socket (``_Deadline``).
# Derived from the configured per-read timeout so the preview path (which lowers it)
# gets a tighter budget than a background crawl, and capped so no setting can hand a
# web worker away for long.
# Override with the `max_fetch_seconds` setting for an absolute value.
FETCH_BUDGET_FACTOR = 3
MAX_FETCH_SECONDS = 30
# Default crawler UA: a current desktop-Chrome string so bot walls that reject bare
# clients serve HTML. Overridable via the CRM Enrichment Settings ``user_agent`` field.
DEFAULT_USER_AGENT = (
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
	"(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class SSRFError(Exception):
	"""Raised internally when a URL fails the SSRF guard. Never escapes ``fetch``."""


# --------------------------------------------------------------------------- #
# SSRF guard
# --------------------------------------------------------------------------- #
def _domain_in_list(host: str, domains: list) -> bool:
	"""True if ``host`` equals or is a subdomain of any entry in ``domains``.

	The trailing dot of a fully-qualified name (``evil.com.``) is stripped from both
	sides -- it resolves identically in DNS, so leaving it on would let ``evil.com.``
	slip past a ``evil.com`` block/allow rule.
	"""
	host = (host or "").lower().split(":")[0].rstrip(".")
	for d in domains:
		d = (d or "").lower().strip().rstrip(".")
		if not d:
			continue
		if host == d or host.endswith("." + d):
			return True
	return False


def _is_blocked_ip(ip: str) -> bool:
	"""True if ``ip`` is not a public (globally-routable) address.

	Mirrors the framework's own SSRF check (``make_safe_get_request`` in
	frappe.utils.safe_exec): ``not is_global`` rejects loopback, private, link-local,
	reserved and unspecified addresses -- and also shared/CGNAT ranges (100.64.0.0/10,
	0.0.0.0/8) that an explicit flag enumeration tends to miss. ``is_global`` does NOT
	cover multicast, so keep an explicit reject for it (the framework helper misses it).
	"""
	try:
		addr = ipaddress.ip_address(ip)
	except ValueError:
		return True  # unparseable -> reject
	return not addr.is_global or addr.is_multicast


def _resolve_ips(host: str) -> list:
	"""Resolve ``host`` to its IP strings via ``socket.getaddrinfo``."""
	infos = socket.getaddrinfo(host, None)
	# index 4 is sockaddr; element 0 is the IP for both AF_INET / AF_INET6.
	return list({info[4][0] for info in infos})


def validate_url(url: str, cfg) -> str:
	"""SSRF guard entry point. Returns the validated URL or raises ``SSRFError``.

	Validates the scheme, then resolves the hostname and rejects any URL that
	resolves to a loopback/private/link-local/reserved address. Honors the
	Settings allow/block domain lists: a blocked domain is always rejected; if an
	allow list exists the host must be on it. The private-network rejection is
	unconditional -- there is no setting to disable it (that would be a pure SSRF
	footgun for a crawler that fetches user-supplied URLs).
	"""
	_validated_ips(url, cfg)
	return url


def _validated_ips(url: str, cfg) -> list:
	"""Run the full SSRF checks for ``url`` and return the resolved, validated IPs.

	The caller connects to one of these exact addresses (see ``_pinned_get``), so
	the IP that was checked is the IP that serves the request. Raises ``SSRFError``
	on any rejection.
	"""
	parsed = urlparse(url)
	if parsed.scheme not in ("http", "https"):
		raise SSRFError(f"unsupported URL scheme: {parsed.scheme or '(none)'}")

	# Strip the trailing dot of a fully-qualified name at the source, so the SAME
	# canonical host feeds the allow/block check AND DNS resolution -- ``evil.com.``
	# resolves identically to ``evil.com`` and must not bypass either.
	host = (parsed.hostname or "").strip().rstrip(".")
	if not host:
		raise SSRFError("URL has no host")

	blocked = cfg.blocked_domains if cfg else []
	allowed = cfg.allowed_domains if cfg else []
	if _domain_in_list(host, blocked):
		raise SSRFError(f"host is on the blocked-domains list: {host}")
	if allowed and not _domain_in_list(host, allowed):
		raise SSRFError(f"host is not on the allowed-domains list: {host}")

	# One answer for "no such name" and "an internal name", and never the address:
	# this text reaches whoever typed the URL, and telling them which internal IP a
	# compose service sits on -- or that the name exists at all -- maps the network
	# for them. The specifics go to the server log.
	not_public = f"host {host} does not resolve to a public address"
	try:
		ips = _resolve_ips(host)
	except socket.gaierror as exc:
		_log_rejection(host, f"could not resolve: {exc}")
		raise SSRFError(not_public) from exc
	if not ips:
		_log_rejection(host, "resolved to nothing")
		raise SSRFError(not_public)
	for ip in ips:
		if _is_blocked_ip(ip):
			_log_rejection(host, f"resolves to a non-public address: {ip}")
			raise SSRFError(not_public)

	# Deterministic order, IPv4 first: the caller pins the first entry, and unlike
	# requests' resolver it won't fall back across address families, so an IPv6
	# answer must not shadow a reachable IPv4 one on v4-only networks.
	return sorted(ips, key=lambda ip: (":" in ip, ip))


def _log_rejection(host: str, detail: str) -> None:
	frappe.logger("crm.enrichment").info(f"SSRF guard rejected {host}: {detail}")


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
def build_session(cfg=None):
	"""Build the crawler session on the framework helper.

	Sets a browser-like header set (User-Agent from Settings + Accept / Sec-Fetch /
	client-hint headers a real browser sends) so servers that reject bare clients
	still serve HTML, and customizes the retry status_forcelist for 429/5xx. Note:
	this only spoofs headers -- the TLS fingerprint is still that of ``requests``
	(see the TLS note in CONTEXT.md).
	"""
	retries = int(cfg.setting("retry_count")) if cfg else 2
	user_agent = cfg.setting("user_agent") if cfg else DEFAULT_USER_AGENT
	session = get_request_session(max_retries=retries)
	# get_request_session only forces 500; widen to the usual transient set.
	try:
		adapter = HTTPAdapter(max_retries=_retry_policy(retries))
		session.mount("http://", adapter)
		session.mount("https://", adapter)
	except Exception:  # pragma: no cover - keep the framework default on any issue
		pass
	session.headers.update(
		{
			"User-Agent": user_agent,
			"Accept": (
				"text/html,application/xhtml+xml,application/xml;q=0.9,"
				"image/avif,image/webp,image/apng,*/*;q=0.8"
			),
			"Accept-Language": "en-US,en;q=0.9",
			# Browser-ish request context so bot walls that check these serve HTML.
			# (Accept-Encoding is left to requests so it only advertises codecs it can
			# actually decode.)
			"Upgrade-Insecure-Requests": "1",
			"Sec-Fetch-Dest": "document",
			"Sec-Fetch-Mode": "navigate",
			"Sec-Fetch-Site": "none",
			"Sec-Fetch-User": "?1",
			"Sec-CH-UA": '"Chromium";v="125", "Not.A/Brand";v="24", "Google Chrome";v="125"',
			"Sec-CH-UA-Mobile": "?0",
			"Sec-CH-UA-Platform": '"Windows"',
		}
	)
	return session


class _BudgetedRetry(Retry):
	"""urllib3's Retry, never sleeping past the running fetch's deadline.

	Retries sleep inside ``adapter.send``, below every check ``fetch`` makes, and with
	no socket open for ``_Deadline`` to shut -- so the backoff is cut to whatever the
	budget has left. (``Retry.new`` rebuilds with ``type(self)``, so this survives
	every retry.)"""

	def get_backoff_time(self) -> float:
		backoff = super().get_backoff_time()
		deadline = _active_deadline()
		if deadline is None:
			return backoff
		return max(0.0, min(backoff, deadline.remaining()))


def _retry_policy(retries: int) -> Retry:
	return _BudgetedRetry(
		total=retries,
		backoff_factor=0.3,
		status_forcelist=RETRY_STATUS_FORCELIST,
		allowed_methods=frozenset(["GET", "HEAD"]),
		# A Retry-After is the server's schedule, not our budget: honoured, one site in
		# maintenance mode (503, Retry-After: 600) held a preview's web worker for
		# twenty minutes, and urllib3 only caps the wait at six hours.
		respect_retry_after_header=False,
		# Once the retries run out, hand back the last answer instead of raising: a
		# persistent 429 is a bot wall, and only its status says so (raised, it came
		# back as status 0 -- "couldn't reach this website").
		raise_on_status=False,
	)


# --------------------------------------------------------------------------- #
# Pinned connections (DNS-rebinding defense)
# --------------------------------------------------------------------------- #
class _PinnedIPAdapter(HTTPAdapter):
	"""Transport adapter for URLs whose netloc was rewritten to a pre-validated IP.

	``server_hostname`` keeps TLS SNI on the original hostname, and urllib3 also
	matches the certificate against it (it falls back to ``server_hostname`` when
	``assert_hostname`` is unset), so pinning does not weaken TLS verification.
	urllib3 strips ``server_hostname`` for plain-HTTP pools, so the same adapter
	serves both schemes.
	"""

	def __init__(self, hostname: str, **kwargs):
		self._server_hostname = hostname
		super().__init__(**kwargs)

	def init_poolmanager(self, *args, **kwargs):
		kwargs["server_hostname"] = self._server_hostname
		super().init_poolmanager(*args, **kwargs)
		# Every connection this adapter opens or reuses reports its socket to the
		# running fetch's deadline (see ``_Deadline``).
		self.poolmanager.pool_classes_by_scheme = {"http": _WatchedHTTPPool, "https": _WatchedHTTPSPool}


# --------------------------------------------------------------------------- #
# The fetch deadline, enforced at the socket
# --------------------------------------------------------------------------- #
_local = threading.local()


def _active_deadline():
	"""The ``_Deadline`` of the fetch running on this thread, if any."""
	return getattr(_local, "deadline", None)


def _shutdown(handle) -> None:
	try:
		handle.shutdown(socket.SHUT_RDWR)
	except OSError:
		pass  # already closed, or never connected


class _Deadline:
	"""One fetch's wall-clock budget, enforced on its sockets rather than between reads.

	A deadline checked between reads does nothing while a read is in progress, and a
	read is where a hostile host keeps us: ``requests``' timeout is per ``recv()`` and
	restarts on every byte, ``iter_content`` blocks until a whole chunk has arrived,
	and the TLS handshake, status line and headers are all read before any of our
	code runs. So a timer shuts down every socket the fetch has touched when the
	budget runs out, which wakes whichever ``recv()`` is blocked, wherever it is.

	Sockets are reported by the watched connection classes below through a
	thread-local, because nothing between ``fetch`` and urllib3's connection is ours
	to pass an argument through. Each is held as a duplicate descriptor:
	``shutdown()`` acts on the socket rather than the descriptor, so it still reaches
	a connection whose original object the TLS wrapper has since taken over, and
	closing our copy closes nothing that urllib3 owns.
	"""

	def __init__(self, seconds: float):
		self.at = time.monotonic() + seconds
		self.expired = False
		self._handles = []
		self._lock = threading.Lock()
		self._timer = threading.Timer(max(seconds, 0), self._expire)
		self._timer.daemon = True

	def remaining(self) -> float:
		return self.at - time.monotonic()

	def watch(self, sock) -> None:
		try:
			handle = socket.fromfd(sock.fileno(), sock.family, sock.type)
		except (OSError, ValueError):
			return  # closed already: nothing left to wait on
		with self._lock:
			self._handles.append(handle)
			expired = self.expired
		if expired:
			# a connection opened after the budget ran out (a retry) gets no grace
			_shutdown(handle)

	def _expire(self) -> None:
		with self._lock:
			self.expired = True
			handles = list(self._handles)
		for handle in handles:
			_shutdown(handle)

	def __enter__(self):
		self._outer = _active_deadline()
		_local.deadline = self
		self._timer.start()
		return self

	def __exit__(self, *exc_info):
		self._timer.cancel()
		# a shutdown already under way finishes before its handles are closed
		self._timer.join()
		_local.deadline = self._outer
		with self._lock:
			handles, self._handles = self._handles, []
		for handle in handles:
			handle.close()


def _watch(sock) -> None:
	deadline = _active_deadline()
	if deadline is not None:
		deadline.watch(sock)


class _WatchedSocketMixin:
	"""Report each socket a connection uses to the running fetch's deadline: a new
	one as soon as it connects (before the TLS handshake, which a host can trickle
	too), and a pooled keep-alive one when a fetch reuses it."""

	def _new_conn(self):
		sock = super()._new_conn()
		_watch(sock)
		return sock

	def request(self, *args, **kwargs):
		if self.sock is not None:
			_watch(self.sock)
		return super().request(*args, **kwargs)


class _WatchedHTTPConnection(_WatchedSocketMixin, HTTPConnection):
	pass


class _WatchedHTTPSConnection(_WatchedSocketMixin, HTTPSConnection):
	pass


class _WatchedHTTPPool(HTTPConnectionPool):
	ConnectionCls = _WatchedHTTPConnection


class _WatchedHTTPSPool(HTTPSConnectionPool):
	ConnectionCls = _WatchedHTTPSConnection


def _pinned_adapter(session, hostname: str, retries: int) -> _PinnedIPAdapter:
	"""Per-hostname adapter cache on the session, so keep-alive pooling survives
	across the pages of a crawl instead of reconnecting for every request."""
	cache = getattr(session, "_pinned_adapters", None)
	if cache is None:
		cache = {}
		session._pinned_adapters = cache
	adapter = cache.get(hostname)
	if adapter is None:
		adapter = _PinnedIPAdapter(hostname, max_retries=_retry_policy(retries))
		cache[hostname] = adapter
	return adapter


def _pinned_get(session, url: str, pinned_ip: str, timeout: int, retries: int):
	"""GET ``url`` connecting to ``pinned_ip`` -- an address the SSRF guard just
	validated -- so a DNS answer that changes between validation and connection
	(rebinding) cannot steer the socket somewhere else. Only the socket target is
	rewritten: the Host header, TLS SNI and certificate verification all stay on
	the original hostname.
	"""
	import requests

	parsed = urlparse(url)
	host = parsed.hostname or ""
	ip_netloc = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
	if parsed.port:
		ip_netloc = f"{ip_netloc}:{parsed.port}"
	host_header = f"{host}:{parsed.port}" if parsed.port else host

	prepared = session.prepare_request(
		requests.Request(
			"GET",
			parsed._replace(netloc=ip_netloc).geturl(),
			headers={"Host": host_header},
		)
	)
	return _pinned_adapter(session, host, retries).send(
		prepared,
		timeout=timeout,
		stream=True,
		verify=session.verify,
		cert=session.cert,
	)


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
_META_CHARSET_RE = re.compile(rb"""charset=["']?\s*([a-zA-Z0-9_\-]+)""", re.IGNORECASE)


def _sniff_html_charset(raw: bytes) -> str | None:
	"""Charset declared in a <meta> tag (handles both `<meta charset=...>` and
	`<meta http-equiv content="...; charset=...">`); None if absent."""
	match = _META_CHARSET_RE.search(raw[:4096])
	if match:
		try:
			return match.group(1).decode("ascii")
		except (UnicodeDecodeError, AttributeError):
			return None
	return None


def _read_capped(resp, max_bytes: int, deadline: float | None = None) -> str:
	"""Read at most ``max_bytes``, and for at most as long as ``deadline`` allows.

	The byte cap alone does not bound the read: ``requests``'s timeout is per socket
	read, and it restarts on every byte, so a host trickling one byte every few
	seconds never trips it and holds the worker until gunicorn kills it. The
	monotonic deadline is the bound that a cooperative-looking server cannot reset.
	Whatever arrived before it is kept and parsed, exactly as for the byte cap: a
	truncated page is still worth extracting from, and the point is to let go of the
	worker.

	Checking the clock between chunks only helps while chunks keep arriving; a read
	blocked mid-chunk is ended by the fetch's ``_Deadline`` shutting the socket. The
	error that read then raises means "out of time", so it ends the read the same way,
	keeping the chunks that completed (the one in flight is lost with the read)."""
	chunks = []
	total = 0
	try:
		for chunk in resp.iter_content(chunk_size=16_384, decode_unicode=False):
			if chunk:
				total += len(chunk)
				chunks.append(chunk)
				if total >= max_bytes:
					break
			# checked on empty chunks too: keep-alive dribble is exactly the shape of
			# traffic that keeps the per-read timeout from ever firing
			if deadline is not None and time.monotonic() >= deadline:
				break
	except Exception:
		guard = _active_deadline()
		if not (guard and guard.expired):
			raise
	raw = b"".join(chunks)
	# requests defaults text/* without an explicit charset to ISO-8859-1, which
	# mojibakes UTF-8 pages that only declare their charset in a <meta> tag. When the
	# header carries no charset, trust the document's own declaration instead.
	if "charset=" in resp.headers.get("Content-Type", "").lower():
		encoding = resp.encoding or "utf-8"
	else:
		encoding = _sniff_html_charset(raw) or "utf-8"
	try:
		return raw.decode(encoding, errors="replace")
	except (LookupError, TypeError):
		return raw.decode("utf-8", errors="replace")


def _fetch_budget(cfg, timeout: int) -> float:
	"""Total wall-clock seconds one ``fetch`` may spend.

	Defaults to a multiple of the per-read timeout so a caller that already asked for
	a short one (the preview path lowers ``request_timeout`` to ``preview_timeout``)
	gets a proportionally short budget, capped by ``MAX_FETCH_SECONDS`` so no setting
	can hand a web worker over for minutes. The ``max_fetch_seconds`` setting
	overrides it outright."""
	configured = cfg.setting("max_fetch_seconds", None) if cfg else None
	if configured:
		return float(configured)
	return float(min(timeout * FETCH_BUDGET_FACTOR, MAX_FETCH_SECONDS))


def _failure(exc: Exception, timeout: int) -> str:
	"""The error text ``fetch`` reports for an exception (it never raises one)."""
	import requests

	if isinstance(exc, requests.exceptions.Timeout):
		return f"timeout after {timeout}s"
	if isinstance(exc, requests.exceptions.TooManyRedirects):
		return "too many redirects"
	if isinstance(exc, requests.exceptions.SSLError):
		return f"ssl error: {exc}"
	if isinstance(exc, requests.exceptions.ConnectionError):
		return f"connection error: {exc}"
	if isinstance(exc, requests.exceptions.RequestException):
		return f"request error: {exc}"
	return f"unexpected error: {exc}"


def fetch(url: str, cfg, session=None, html_only: bool = True):
	"""Fetch a URL and return ``(status_code, html, error, final_url)``.

	Never raises -- any failure (SSRF rejection, timeout, non-HTML, oversized) is
	reported as a non-empty ``error`` string with ``status_code`` 0 (or the actual
	status for content-type skips). Redirects are followed manually so the resolved
	IP of every hop is re-validated by the SSRF guard; ``final_url`` is the URL that
	actually served the body (post-redirect), so callers resolve relative links and
	record provenance against the right host. Pass ``html_only=False`` to accept
	non-HTML bodies (e.g. ``text/plain`` robots.txt).

	SSRF note: each hop connects to the exact IP the guard validated for it
	(``_pinned_get``), so a DNS-rebinding host (short TTL, alternating answers)
	cannot pass validation with a public address and serve the request from a
	private one.
	"""
	import requests

	timeout = int(cfg.setting("request_timeout")) if cfg else 10
	max_bytes = int(cfg.setting("max_download_bytes")) if cfg else 3_000_000
	retries = int(cfg.setting("retry_count")) if cfg else 2
	budget = _fetch_budget(cfg, timeout)
	over_budget = f"exceeded the {budget:g}s fetch budget"
	deadline = _Deadline(budget)

	own_session = session is None
	session = session or build_session(cfg)
	current = url
	try:
		with deadline:
			for _hop in range(MAX_REDIRECTS + 1):
				remaining = deadline.remaining()
				if remaining <= 0:
					# A redirect chain of slow hops spends the budget just as effectively
					# as one slow body, so the deadline is checked per hop as well.
					return 0, "", over_budget, current
				try:
					ips = _validated_ips(current, cfg)
				except SSRFError as exc:
					return 0, "", f"blocked by SSRF guard: {exc}", current

				# Redirects are followed manually (each hop re-validated and re-pinned).
				# No single hop may outlast the budget the whole fetch has left.
				resp = _pinned_get(session, current, ips[0], min(timeout, remaining), retries)

				if resp.is_redirect or resp.is_permanent_redirect:
					location = resp.headers.get("Location")
					resp.close()
					if not location:
						return resp.status_code, "", "redirect without Location header", current
					current = requests.compat.urljoin(current, location)
					continue

				content_type = resp.headers.get("Content-Type", "").lower()
				if html_only and content_type and not any(ct in content_type for ct in HTML_CONTENT_TYPES):
					status = resp.status_code
					resp.close()
					return status, "", f"skipped non-HTML content-type: {content_type}", current

				html = _read_capped(resp, max_bytes, deadline.at)
				status = resp.status_code
				resp.close()
				if deadline.expired and not html:
					# Cut off before a whole chunk arrived -- or mid-headers, which
					# http.client takes for a complete, empty response. Either way the
					# host was too slow, not empty, and a blank 200 would be read as a
					# JavaScript-only page.
					return 0, "", over_budget, current
				return status, html, "", current

			return 0, "", "too many redirects", current
	except Exception as exc:
		if deadline.expired:
			# whatever broke, it broke because the deadline shut the socket under it
			return 0, "", over_budget, current
		return 0, "", _failure(exc, timeout), current
	finally:
		if own_session:
			session.close()
