import hashlib
import json
import time
from contextlib import contextmanager, suppress

import frappe
import redis
import requests
from frappe import _

from crm.integrations.remote_url import RemoteHostNotAllowed, ensure_host_allowed

TOKEN_CACHE_PREFIX = "acumatica_token::"


def token_cache_key(base: str, client_id: str | None, username: str | None) -> str:
	"""Where the sync's shared token is cached: one per login, not one per instance.

	One instance URL serves every company on it -- MBP's Sandbox and live share
	https://mbp.brilliantcloud.online/MBP, and the client ID's @Tenant suffix is what
	picks the company. Keyed on the URL alone, a token minted for the Sandbox outlived
	the switch to live: new credentials were saved, and the sync went on reading (and
	the quote button writing to) the Sandbox until that token expired an hour later.
	Hashed so the cache key never carries the login's names in the clear.
	"""
	login = hashlib.sha256(f"{client_id or ''}\0{username or ''}".encode()).hexdigest()[:16]
	return f"{TOKEN_CACHE_PREFIX}{base.rstrip('/')}::{login}"


TIMEOUT = 30
# The token request, as (connect, read): requests applies a bare number to each in
# turn, so "30" was up to 60 seconds, and a quote click's login has to fit in what
# outbound._quote_write_timeout keeps back from the proxy's deadline.
LOGIN_TIMEOUT = (5, 25)
# One login at a time per API user (see AcumaticaClient._token). The lock outlives the
# slowest token request, so it cannot lapse under a login still in flight, and a
# worker killed mid-login holds the others out for no longer than this.
LOGIN_LOCK_SECONDS = sum(LOGIN_TIMEOUT) + 15
# How long a caller waits for somebody else's login before giving up. A job can sit
# out the whole of it. A request cannot: the wait and a login of the caller's own
# (the holder's failed) both come out of the TIMEOUT + 15 the quote PUT leaves.
LOGIN_WAIT_IN_JOB = LOGIN_LOCK_SECONDS
LOGIN_WAIT_IN_REQUEST = 10
# What became of the login lock.
_HELD, _BUSY, _NO_REDIS = "held", "busy", "no redis"
# A SalesOrder PUT runs the tenant's whole order pipeline (pricing, tax, customisations)
# and routinely outlasts a read. Timing out a write that then succeeds is the expensive
# mistake: the deal never learns its OrderNbr, and the rep's retry makes a second order.
WRITE_TIMEOUT = 120
_DETAIL_KEYS = ("error", "exceptionMessage", "message")


class AcumaticaError(Exception):
	def __init__(self, message, status_code=None, body=None):
		super().__init__(message)
		self.status_code = status_code
		self.body = body

	def detail(self, limit=500):
		"""The human-readable reason inside the response body.

		Acumatica answers a rejected PUT by echoing the entity back with an `error` key
		nested inside whichever field failed, so the reason sits arbitrarily deep and
		cutting the raw body at N characters usually cuts it off. Walk the JSON for it;
		fall back to the raw text for a body that is not JSON (a proxy's HTML page)."""
		body = self.body or ""
		try:
			parsed = json.loads(body) if isinstance(body, str) else body
		except ValueError:
			return str(body)[:limit]
		found = []

		def walk(node, path):
			if isinstance(node, dict):
				for key, val in node.items():
					if key in _DETAIL_KEYS and isinstance(val, str) and val.strip():
						msg = f"{path}: {val.strip()}" if path and key == "error" else val.strip()
						if msg not in found:
							found.append(msg)
					else:
						walk(val, key if isinstance(val, dict) else path)
			elif isinstance(node, list):
				for item in node:
					walk(item, path)

		walk(parsed, "")
		return ("; ".join(found) or str(body))[:limit]


class AcumaticaAuthError(AcumaticaError):
	"""The login itself was refused: a fact about the credentials, not about any record."""


def v(rec, field, default=None):
	"""Unwrap Acumatica's {"value": x} field encoding."""
	wrapped = (rec or {}).get(field)
	if not isinstance(wrapped, dict):
		return default
	return wrapped.get("value", default)


def wrap(payload):
	"""Wrap plain values into Acumatica's {"value": x} encoding, recursing into child lists."""
	out = {}
	for key, val in payload.items():
		if isinstance(val, list):
			out[key] = [wrap(item) for item in val]
		elif isinstance(val, dict):
			out[key] = val  # already wrapped or a nested entity
		else:
			out[key] = {"value": val}
	return out


class AcumaticaClient:
	def __init__(self, settings, shared_session=True):
		self.settings = settings
		self.base = settings.instance_url.rstrip("/")
		# Every process shares one cached token per login. A client that is not part
		# of the sync (Test connection) keeps its own instead: it must not test the
		# credentials behind somebody else's cached login, and dropping that login from
		# the cache would not end it -- the sync would mint another and the dropped one
		# would sit in an API login slot until it expired.
		self.shared_session = shared_session
		self._own_token = None

	def entity_url(self, entity):
		s = self.settings
		return f"{self.base}/entity/{s.endpoint_name}/{s.endpoint_version}/{entity}"

	# --- auth -----------------------------------------------------------
	def _cache_key(self):
		return token_cache_key(self.base, self.settings.client_id, self.settings.username)

	def _shared_token(self):
		# From redis itself: this process's copy of the key cannot see the sync's
		# logout, or the login another worker made since.
		return frappe.cache().get_value(self._cache_key(), use_local_cache=False)

	def _cached_token(self):
		if not self.shared_session:
			return self._own_token
		# _own_token on a shared client is the login it made while redis was away
		return self._shared_token() or self._own_token

	@staticmethod
	def _login_wait():
		in_request = getattr(frappe.local, "request", None) is not None
		return LOGIN_WAIT_IN_REQUEST if in_request else LOGIN_WAIT_IN_JOB

	@contextmanager
	def _login_lock(self):
		"""Hold the shared login's lock. Yields _HELD; _BUSY when the wait ran out
		with somebody else still holding it; _NO_REDIS when there is no lock to take."""
		lock, state = None, _NO_REDIS
		try:
			lock = frappe.cache().lock(
				frappe.cache().make_key(f"{self._cache_key()}::login"),
				timeout=LOGIN_LOCK_SECONDS,
				blocking_timeout=self._login_wait(),
			)
			state = _HELD if lock.acquire() else _BUSY
		except redis.exceptions.RedisError:
			pass
		try:
			yield state
		finally:
			if state == _HELD:
				# expired under a login slower than any should be, and taken by
				# somebody else: theirs now
				with suppress(redis.exceptions.RedisError):
					lock.release()

	def _token(self, rejected=None):
		"""The token to send. ``rejected`` is one Acumatica just answered 401 to.

		The API user has three concurrent logins (see ``logout``). Every caller that
		found the cache empty used to open one of its own -- the sweep ends by logging
		out, with the pushes it queued and a rep's quote click in flight -- and each
		caller a 401 reached dropped the cached token, the one another worker had just
		stored included. So a login is made under a lock and looked for again once the
		lock is held: the first caller logs in, the rest use what it stored."""
		cached = self._cached_token()
		if cached and cached != rejected:
			return cached
		if not self.shared_session:
			return self._login()
		with self._login_lock() as lock:
			cached = self._cached_token()
			if cached and cached != rejected:
				return cached
			if lock == _BUSY:
				# Somebody else's login is still in flight -- the token endpoint is
				# hanging. Logging in beside it is how several workers took the API
				# user's three logins at once; nothing has been sent, so the caller
				# fails cleanly and the next job, sweep or click tries again.
				message = "Another worker is still signing in to Acumatica; try again in a minute"
				raise AcumaticaAuthError(message, body=message)
			if cached:
				# the refused token itself: a login that fails must not leave it behind
				self._forget_token(cached)
			token = self._login()
			if lock == _NO_REDIS:
				# With redis away the token was cached nowhere, and every call of the
				# run would log in again -- three pages are the user's three logins,
				# none of them where logout() could find it. This client keeps it.
				self._own_token = token
			return token

	def _login(self):
		s = self.settings
		# Asked here, where the secrets are about to leave: the URL was checked when
		# it was saved, but a name can be re-pointed since, and a URL saved before
		# that check existed was never looked at.
		try:
			ensure_host_allowed(self.base, _("Instance URL"))
		except RemoteHostNotAllowed as e:
			raise AcumaticaAuthError(str(e)) from e
		data = {
			"grant_type": "password",
			"client_id": s.client_id,
			"client_secret": s.get_password("client_secret", raise_exception=False),
			"username": s.username,
			"password": s.get_password("password", raise_exception=False),
			"scope": "api",
		}
		if getattr(s, "branch", None):
			# Tenants with more than one branch reject a login that doesn't name one.
			data["branch"] = s.branch
		resp = requests.post(
			f"{self.base}/identity/connect/token",
			data=data,
			timeout=LOGIN_TIMEOUT,
		)
		if resp.status_code != 200:
			raise AcumaticaAuthError(
				"Acumatica token request failed", status_code=resp.status_code, body=resp.text
			)
		body = resp.json()
		token = body["access_token"]
		# `or 3600`, not a dict default: instances that answer with "expires_in": null
		# would blow up int(None).
		ttl = max(int(body.get("expires_in") or 3600) - 60, 60)
		if self.shared_session:
			frappe.cache().set_value(self._cache_key(), token, expires_in_sec=ttl)
		else:
			self._own_token = token
		return token

	def _forget_token(self, token):
		"""Drop ``token`` -- and only it: the shared key may hold a newer login by now."""
		if not self.shared_session or self._own_token == token:
			self._own_token = None
		if self.shared_session and self._shared_token() == token:
			frappe.cache().delete_value(self._cache_key())

	def _request(self, method, url, timeout=None, **kw):
		"""One call with a single re-auth retry on 401."""
		timeout = timeout or (TIMEOUT if method == "get" else WRITE_TIMEOUT)
		rejected = None
		for attempt in (0, 1):
			token = self._token(rejected=rejected)
			headers = kw.pop("headers", {}) or {}
			headers["Authorization"] = f"Bearer {token}"
			branch = getattr(self.settings, "branch", None)
			if branch:
				# Under OAuth there is no session to carry a branch: Acumatica reads it
				# from this header on every request, and without it a quote lands in
				# the API user's default branch.
				headers["PX-CbApiBranch"] = branch
			fn = getattr(requests, method)
			resp = fn(url, headers=headers, timeout=timeout, **dict(kw))
			if resp.status_code == 401 and attempt == 0:
				# _token drops it, unless another worker has already logged in again
				rejected = token
				continue
			if resp.status_code >= 400:
				raise AcumaticaError(
					f"Acumatica {method.upper()} {url} -> {resp.status_code}",
					status_code=resp.status_code,
					body=resp.text,
				)
			return resp
		raise AcumaticaError("unreachable")  # pragma: no cover

	def logout(self):
		"""End the API session behind the cached token, and forget the token.

		A token holds one of the user's concurrent API logins (Users, SM201010)
		until it expires, an hour later. Test connection minted one per click and
		a sync one per run, none of them released; the tenant's limit was reached
		on the first day of testing and every later call answered with the login
		page. Best effort and never raises: it runs in finally blocks, and a logout
		that fails must not turn a finished sync or a successful ping into an error.
		A client with its own session ends that one and leaves the shared token alone;
		a shared client also ends the login it made for itself while redis was away.
		"""
		shared = self._shared_token() if self.shared_session else None
		for token in dict.fromkeys(t for t in (shared, self._own_token) if t):
			try:
				self._forget_token(token)
				requests.post(
					f"{self.base}/entity/auth/logout",
					headers={"Authorization": f"Bearer {token}"},
					timeout=TIMEOUT,
				)
			except Exception:
				# the session then expires on its own, which is where we were before
				frappe.logger("crm.acumatica").info("Acumatica logout failed; the session will expire")

	# --- reads ----------------------------------------------------------
	def get_page(self, entity, top=100, skip=0, filter=None, select=None, expand=None, orderby="NoteID"):
		# $skip paging over an unordered result set is undefined -- the server may return
		# a record twice and skip another. NoteID is stable and present on every entity.
		params = {"$top": top, "$skip": skip}
		if orderby:
			params["$orderby"] = orderby
		if filter:
			params["$filter"] = filter
		if select:
			params["$select"] = select
		if expand:
			params["$expand"] = expand
		return self._request("get", self.entity_url(entity), params=params).json()

	def get_by_id(self, entity, record_id):
		"""One record by its `id` (the NoteID), or None when Acumatica no longer has it."""
		try:
			return self._request("get", f"{self.entity_url(entity)}/{record_id}").json()
		except AcumaticaError as e:
			if e.status_code == 404:
				return None
			raise

	def iter_all(self, entity, page_size=100, **kw):
		skip = 0
		while True:
			page = self.get_page(entity, top=page_size, skip=skip, **kw)
			yield from page
			# Stop on an EMPTY page, never on a short one: an API licence tier can cap the
			# rows per response below $top, and treating that cap as the end of the data
			# silently truncates the backfill. Advance by what actually arrived.
			if not page:
				return
			skip += len(page)
			pause = float(self.settings.request_pause or 0)
			if pause:
				time.sleep(pause)

	# --- writes ---------------------------------------------------------
	def put(self, entity, payload, timeout=None):
		"""``timeout`` overrides WRITE_TIMEOUT for a write that has a deadline of its own."""
		return self._request("put", self.entity_url(entity), json=wrap(payload), timeout=timeout).json()

	# --- diagnostics ------------------------------------------------------
	def ping(self):
		"""One cheap, read-only call an admin's "Test connection" button can afford to
		make synchronously. Errors are left to propagate -- the caller is the one that
		knows whether to swallow them for a status panel or let them surface."""
		# No $orderby: one row needs no order, and the button that tells an admin whether
		# the credentials work should not also depend on a query option.
		page = self.get_page("Customer", top=1, select="CustomerID", orderby=None)
		return {"ok": True, "sample": v(page[0], "CustomerID") if page else None}
