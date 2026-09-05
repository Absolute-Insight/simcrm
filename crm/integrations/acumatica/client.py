import time

import frappe
import requests

TOKEN_CACHE_PREFIX = "acumatica_token::"
TIMEOUT = 30


class AcumaticaError(Exception):
	def __init__(self, message, status_code=None, body=None):
		super().__init__(message)
		self.status_code = status_code
		self.body = body


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
	def __init__(self, settings):
		self.settings = settings
		self.base = settings.instance_url.rstrip("/")

	def entity_url(self, entity):
		s = self.settings
		return f"{self.base}/entity/{s.endpoint_name}/{s.endpoint_version}/{entity}"

	# --- auth -----------------------------------------------------------
	def _cache_key(self):
		return f"{TOKEN_CACHE_PREFIX}{self.base}"

	def _token(self, force=False):
		if not force:
			cached = frappe.cache().get_value(self._cache_key())
			if cached:
				return cached
		s = self.settings
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
			timeout=TIMEOUT,
		)
		if resp.status_code != 200:
			raise AcumaticaError(
				"Acumatica token request failed", status_code=resp.status_code, body=resp.text
			)
		body = resp.json()
		token = body["access_token"]
		# `or 3600`, not a dict default: instances that answer with "expires_in": null
		# would blow up int(None).
		ttl = max(int(body.get("expires_in") or 3600) - 60, 60)
		frappe.cache().set_value(self._cache_key(), token, expires_in_sec=ttl)
		return token

	def _request(self, method, url, **kw):
		"""One call with a single re-auth retry on 401."""
		for attempt in (0, 1):
			token = self._token(force=attempt == 1)
			headers = kw.pop("headers", {}) or {}
			headers["Authorization"] = f"Bearer {token}"
			fn = getattr(requests, method)
			resp = fn(url, headers=headers, timeout=TIMEOUT, **dict(kw))
			if resp.status_code == 401 and attempt == 0:
				frappe.cache().delete_value(self._cache_key())
				continue
			if resp.status_code >= 400:
				raise AcumaticaError(
					f"Acumatica {method.upper()} {url} -> {resp.status_code}",
					status_code=resp.status_code,
					body=resp.text,
				)
			return resp
		raise AcumaticaError("unreachable")  # pragma: no cover

	# --- reads ----------------------------------------------------------
	def get_page(self, entity, top=100, skip=0, filter=None, select=None, expand=None, orderby="NoteID"):
		# $skip paging over an unordered result set is undefined -- the server may return
		# a record twice and skip another. NoteID is stable and present on every entity.
		params = {"$top": top, "$skip": skip, "$orderby": orderby}
		if filter:
			params["$filter"] = filter
		if select:
			params["$select"] = select
		if expand:
			params["$expand"] = expand
		return self._request("get", self.entity_url(entity), params=params).json()

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
	def put(self, entity, payload):
		return self._request("put", self.entity_url(entity), json=wrap(payload)).json()
