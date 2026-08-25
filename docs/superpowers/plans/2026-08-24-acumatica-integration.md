# Acumatica Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two-way integration between Vectora CRM and Acumatica ERP: backfill the client's existing Customers/Contacts/Stock Items into Vectora, keep them fresh (nightly sweep + optional webhooks), and push new Customers and Sales Quotes from deals back into Acumatica.

**Architecture:** A sibling module `crm/integrations/acumatica/` beside `crm/integrations/erpnext/` — one ERP per deployment, no shared abstraction. System-of-record per entity: Acumatica owns Customers/Contacts/Items (they flow in, read-mostly); Vectora owns Leads/Deals (deal events push out). Identity is Acumatica's `NoteID` GUID stored in custom fields on CRM records; all remote writes are PUT-upserts keyed on it. A nightly incremental sweep on `LastModifiedDateTime` is the correctness mechanism; webhooks (Acumatica Push Notifications) are only a latency upgrade — Acumatica retains failed notifications for 2 days, so the sweep is not optional.

**Tech Stack:** Frappe DocTypes (Single settings + child table), `requests` (already a frappe dependency), OAuth 2.0 password grant against `{instance}/identity/connect/token`, Acumatica contract-based REST (`/entity/{endpoint}/{version}/{Entity}`, OData-style `$filter/$top/$skip/$expand`, fields wrapped as `{"value": ...}`).

**Spec:** The decisions section below — this plan is self-contained; there is no separate spec document. Decided with the user on 2026-08-24: (1) one ERP per deployment, no provider abstraction; (2) two-way sync — the client's existing Acumatica data must appear in Vectora; (3) plan chooses the optimal mechanics.

## Global Constraints

- Python is **tab-indented** (frappe convention). Match `crm/integrations/erpnext/utils.py` style.
- Python tests: `FrappeTestCase` from `frappe.tests.utils`; run on **`test_site`, never `dev.localhost`** (`bench --site test_site run-tests --module <module>` from `/workspace/frappe-bench`).
- All HTTP in tests is mocked with `unittest.mock.patch` — no test may contact a real Acumatica.
- Commits: `feat:`/`fix:`/`test:`/`docs:`, one per coherent change. Pre-commit hooks rewrite files: `git add` the result and re-commit. Hooks block committing on `develop` — work on branch `feat/acumatica-integration`.
- `setFieldProperty`, `formDialog`, injected script helpers, lifecycle hook names are public API — additive changes only. (This plan only *adds* a Form Script, so no risk.)
- Frontend: `cd /workspace/frontend && yarn test:run` must stay green (446 tests at time of writing; re-read the count from output).
- The DocType `ERPNext CRM Settings` and module `crm/integrations/erpnext/` are **not** touched by this plan.
- Field values from Acumatica arrive wrapped: `{"CustomerID": {"value": "ABC"}}`. Never read `rec["CustomerID"]` directly — always unwrap via the `v()` helper defined in Task 2.
- Mutual exclusion: `CRM Acumatica Settings.enabled` and `ERPNext CRM Settings.enabled` may not both be 1 (enforced in Task 1's `validate`).

## Verification commands (used throughout)

```bash
cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_client
cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_importer
cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_outbound
cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_webhook
cd /workspace/frappe-bench && bench --site test_site run-tests --app crm      # full suite before the final commit
cd /workspace/frontend && yarn test:run
pre-commit run --files <changed files>
```

After adding/altering any DocType JSON: `cd /workspace/frappe-bench && bench --site test_site migrate` (the test bench serves this working tree via symlink; new doctypes don't exist until migrate).

---

### Task 1: Settings DocType — `CRM Acumatica Settings` + sync-issue child table

**Files:**
- Create: `crm/fcrm/doctype/crm_acumatica_settings/__init__.py` (empty)
- Create: `crm/fcrm/doctype/crm_acumatica_settings/crm_acumatica_settings.json`
- Create: `crm/fcrm/doctype/crm_acumatica_settings/crm_acumatica_settings.py`
- Create: `crm/fcrm/doctype/crm_acumatica_sync_issue/__init__.py` (empty)
- Create: `crm/fcrm/doctype/crm_acumatica_sync_issue/crm_acumatica_sync_issue.json`
- Test: `crm/fcrm/doctype/crm_acumatica_settings/test_crm_acumatica_settings.py`

**Interfaces:**
- Produces: Single DocType `CRM Acumatica Settings` with fields listed below; `get_settings() -> Document` (module-level, cached via `frappe.get_cached_doc`); `record_sync_issue(entity: str, remote_id: str, kind: str, detail: str) -> None`; `ensure_custom_fields() -> None` (called on enable; body in Task 3).
- Consumes: nothing.

Fields for `crm_acumatica_settings.json` (Single, `"issingle": 1`, module `FCRM`):

| fieldname | fieldtype | notes |
|---|---|---|
| enabled | Check | default "0" |
| instance_url | Data | e.g. `https://tenant.acumatica.com` — reqd_if enabled |
| endpoint_name | Data | default "Default" |
| endpoint_version | Data | default "24.200.001" — instances differ; the connection test surfaces the right one |
| client_id | Data | OAuth connected application |
| client_secret | Password | |
| username | Data | API user |
| password | Password | |
| branch | Data | optional; sent as body param on token request if set |
| customer_numbering | Select | `AutoNumber\nFrom Organization Name` — default "AutoNumber" |
| create_customer_on_status_change | Check | default "0" |
| deal_status | Link | options `CRM Deal Status` — depends_on `create_customer_on_status_change` |
| quote_order_type | Data | default "QT" — the Sales Order type used for quotes on that instance |
| webhook_verify_token | Data | random secret the operator pastes into the Push Notification header/URL |
| request_pause | Float | default "0.2" — seconds between pages; API licences cap request rates |
| last_synced_at | Datetime | read_only — high-water mark, written by the sweep |
| sync_issues | Table | options `CRM Acumatica Sync Issue`, read_only |

Fields for `crm_acumatica_sync_issue.json` (child table, `"istable": 1`): `entity` (Data), `remote_id` (Data), `kind` (Select: `Import Failed\nPush Failed\nMapping Conflict`), `detail` (Small Text), `detected_on` (Datetime), `dismissed` (Check). Mirror the shape of `crm/fcrm/doctype/crm_product_sync_issue/crm_product_sync_issue.json` — copy that file and adjust fields; keep its `permissions` block.

For the settings JSON, copy `crm/fcrm/doctype/crm_exotel_settings/crm_exotel_settings.json` as the structural template (Single + Password fields + permissions) and replace the field list.

- [ ] **Step 1: Write the failing tests**

```python
# crm/fcrm/doctype/crm_acumatica_settings/test_crm_acumatica_settings.py
import frappe
from frappe.tests.utils import FrappeTestCase


class TestAcumaticaSettings(FrappeTestCase):
	def tearDown(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.db.set_single_value("ERPNext CRM Settings", "enabled", 0)

	def test_doctype_exists_with_expected_fields(self):
		meta = frappe.get_meta("CRM Acumatica Settings")
		for fieldname in (
			"enabled", "instance_url", "endpoint_name", "endpoint_version",
			"client_id", "client_secret", "username", "password",
			"quote_order_type", "webhook_verify_token", "request_pause",
			"last_synced_at", "sync_issues",
		):
			self.assertIsNotNone(meta.get_field(fieldname), fieldname)
		self.assertEqual(meta.get_field("endpoint_version").default, "24.200.001")

	def test_cannot_enable_both_erps(self):
		frappe.db.set_single_value("ERPNext CRM Settings", "enabled", 1)
		s = frappe.get_doc("CRM Acumatica Settings")
		s.enabled = 1
		s.instance_url = "https://x.acumatica.com"
		with self.assertRaises(frappe.ValidationError):
			s.save()

	def test_enable_requires_instance_url(self):
		s = frappe.get_doc("CRM Acumatica Settings")
		s.enabled = 1
		s.instance_url = ""
		with self.assertRaises(frappe.ValidationError):
			s.save()

	def test_record_sync_issue_appends_row(self):
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
			record_sync_issue,
		)
		before = len(frappe.get_doc("CRM Acumatica Settings").sync_issues)
		record_sync_issue("Customer", "ABC001", "Import Failed", "boom")
		after = frappe.get_doc("CRM Acumatica Settings").sync_issues
		self.assertEqual(len(after), before + 1)
		self.assertEqual(after[-1].entity, "Customer")
		self.assertEqual(after[-1].kind, "Import Failed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.fcrm.doctype.crm_acumatica_settings.test_crm_acumatica_settings`
Expected: import error / `DoesNotExistError: DocType CRM Acumatica Settings` (module and doctype don't exist yet).

- [ ] **Step 3: Create both DocType JSONs and the controller**

Create the two doctype folders with `__init__.py`. Author the JSONs per the field tables above (copying the named templates). Controller:

```python
# crm/fcrm/doctype/crm_acumatica_settings/crm_acumatica_settings.py
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class CRMAcumaticaSettings(Document):
	def validate(self):
		if not self.enabled:
			return
		if not self.instance_url:
			frappe.throw(_("Instance URL is required to enable the Acumatica integration"))
		self.instance_url = self.instance_url.rstrip("/")
		if frappe.db.get_single_value("ERPNext CRM Settings", "enabled"):
			frappe.throw(_("Disable the SIMERP integration first — one ERP integration may be active at a time"))

	def on_update(self):
		if self.enabled:
			from crm.integrations.acumatica.install import ensure_custom_fields

			ensure_custom_fields()


def get_settings():
	return frappe.get_cached_doc("CRM Acumatica Settings")


def record_sync_issue(entity: str, remote_id: str, kind: str, detail: str) -> None:
	"""Append a row to the sync-issues table without touching the rest of the doc."""
	doc = frappe.get_doc("CRM Acumatica Settings")
	doc.append(
		"sync_issues",
		{
			"entity": entity,
			"remote_id": remote_id,
			"kind": kind,
			"detail": detail[:500],
			"detected_on": now_datetime(),
		},
	)
	doc.save(ignore_permissions=True)
```

Also create `crm/integrations/acumatica/__init__.py` (empty) and `crm/integrations/acumatica/install.py` with a stub so `on_update` imports cleanly (real body lands in Task 3):

```python
# crm/integrations/acumatica/install.py
def ensure_custom_fields() -> None:
	"""Custom fields are created in Task 3; keep enable working until then."""
	pass
```

- [ ] **Step 4: Migrate and run the tests**

Run: `cd /workspace/frappe-bench && bench --site test_site migrate && bench --site test_site run-tests --module crm.fcrm.doctype.crm_acumatica_settings.test_crm_acumatica_settings`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add crm/fcrm/doctype/crm_acumatica_settings crm/fcrm/doctype/crm_acumatica_sync_issue crm/integrations/acumatica
git commit -m "feat: CRM Acumatica Settings doctype with sync-issue table"
```

---

### Task 2: REST client — OAuth token, paged reads, PUT-upsert

**Files:**
- Create: `crm/integrations/acumatica/client.py`
- Test: `crm/integrations/acumatica/test_client.py`

**Interfaces:**
- Consumes: `get_settings()` from Task 1.
- Produces (exact signatures — later tasks import these):
  - `v(rec: dict, field: str, default=None)` — unwrap `{"value": x}`; returns `default` when the field or value is absent.
  - `wrap(payload: dict) -> dict` — `{"CustomerName": "Acme"}` → `{"CustomerName": {"value": "Acme"}}` (non-dict leaves only; a list value maps `wrap` over its elements for child collections).
  - `class AcumaticaError(Exception)` with `.status_code` and `.body` attributes.
  - `class AcumaticaClient:` constructed as `AcumaticaClient(settings)`;
    - `.get_page(entity: str, top: int = 100, skip: int = 0, filter: str | None = None, select: str | None = None, expand: str | None = None) -> list[dict]`
    - `.iter_all(entity: str, page_size: int = 100, **kw)` — generator yielding records across pages, sleeping `settings.request_pause` between pages, stopping when a page comes back short.
    - `.put(entity: str, payload: dict) -> dict` — PUT-upsert; payload passed through `wrap()`.
    - `.entity_url(entity: str) -> str` — `{instance_url}/entity/{endpoint_name}/{endpoint_version}/{entity}`.

Token handling: POST `{instance_url}/identity/connect/token` with `grant_type=password`, `client_id`, `client_secret`, `username`, `password`, `scope=api` (form-encoded). Cache the access token in `frappe.cache()` under key `acumatica_token::{instance_url}` with TTL `expires_in - 60`; on a 401 from any API call, drop the cached token, re-authenticate once, retry once, then raise `AcumaticaError`.

- [ ] **Step 1: Write the failing tests**

```python
# crm/integrations/acumatica/test_client.py
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica.client import AcumaticaClient, AcumaticaError, v, wrap


def _resp(status=200, json_body=None):
	m = MagicMock()
	m.status_code = status
	m.json.return_value = json_body if json_body is not None else {}
	m.text = str(json_body)
	return m


def _settings():
	s = MagicMock()
	s.instance_url = "https://t.acumatica.com"
	s.endpoint_name = "Default"
	s.endpoint_version = "24.200.001"
	s.client_id = "cid"
	s.username = "api"
	s.request_pause = 0
	s.get_password.return_value = "secret"
	return s


class TestValueHelpers(unittest.TestCase):
	def test_v_unwraps_value(self):
		self.assertEqual(v({"CustomerID": {"value": "ABC"}}, "CustomerID"), "ABC")

	def test_v_missing_returns_default(self):
		self.assertIsNone(v({}, "CustomerID"))
		self.assertEqual(v({"X": {}}, "X", "d"), "d")

	def test_wrap_wraps_leaves_and_lists(self):
		out = wrap({"CustomerName": "Acme", "Details": [{"InventoryID": "W1"}]})
		self.assertEqual(out["CustomerName"], {"value": "Acme"})
		self.assertEqual(out["Details"][0]["InventoryID"], {"value": "W1"})


class TestClient(FrappeTestCase):
	def setUp(self):
		frappe.cache().delete_value("acumatica_token::https://t.acumatica.com")

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_get_page_authenticates_then_fetches(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		rget.return_value = _resp(200, [{"CustomerID": {"value": "A"}}])
		c = AcumaticaClient(_settings())
		page = c.get_page("Customer", top=5)
		self.assertEqual(v(page[0], "CustomerID"), "A")
		token_url = rpost.call_args[0][0]
		self.assertEqual(token_url, "https://t.acumatica.com/identity/connect/token")
		get_url = rget.call_args[0][0]
		self.assertEqual(get_url, "https://t.acumatica.com/entity/Default/24.200.001/Customer")
		self.assertEqual(rget.call_args.kwargs["params"]["$top"], 5)
		self.assertEqual(rget.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_401_reauthenticates_once_then_raises(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		rget.return_value = _resp(401, {})
		c = AcumaticaClient(_settings())
		with self.assertRaises(AcumaticaError):
			c.get_page("Customer")
		self.assertEqual(rpost.call_count, 2)  # initial + one re-auth
		self.assertEqual(rget.call_count, 2)  # initial + one retry

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_iter_all_pages_until_short_page(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		full = [{"CustomerID": {"value": f"C{i}"}} for i in range(2)]
		rget.side_effect = [_resp(200, full), _resp(200, full[:1])]
		c = AcumaticaClient(_settings())
		got = list(c.iter_all("Customer", page_size=2))
		self.assertEqual(len(got), 3)
		self.assertEqual(rget.call_args_list[1].kwargs["params"]["$skip"], 2)

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.put")
	def test_put_wraps_payload(self, rput, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		rput.return_value = _resp(200, {"NoteID": {"value": "guid-1"}})
		c = AcumaticaClient(_settings())
		out = c.put("Customer", {"CustomerName": "Acme"})
		self.assertEqual(v(out, "NoteID"), "guid-1")
		sent = rput.call_args.kwargs["json"]
		self.assertEqual(sent["CustomerName"], {"value": "Acme"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_client`
Expected: `ModuleNotFoundError`/`ImportError` — `client.py` doesn't exist.

- [ ] **Step 3: Implement the client**

```python
# crm/integrations/acumatica/client.py
import time

import requests

import frappe

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
		resp = requests.post(
			f"{self.base}/identity/connect/token",
			data={
				"grant_type": "password",
				"client_id": s.client_id,
				"client_secret": s.get_password("client_secret", raise_exception=False),
				"username": s.username,
				"password": s.get_password("password", raise_exception=False),
				"scope": "api",
			},
			timeout=TIMEOUT,
		)
		if resp.status_code != 200:
			raise AcumaticaError(
				"Acumatica token request failed", status_code=resp.status_code, body=resp.text
			)
		body = resp.json()
		token = body["access_token"]
		ttl = max(int(body.get("expires_in", 3600)) - 60, 60)
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
	def get_page(self, entity, top=100, skip=0, filter=None, select=None, expand=None):
		params = {"$top": top, "$skip": skip}
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
			if len(page) < page_size:
				return
			skip += page_size
			pause = float(self.settings.request_pause or 0)
			if pause:
				time.sleep(pause)

	# --- writes ---------------------------------------------------------
	def put(self, entity, payload):
		return self._request("put", self.entity_url(entity), json=wrap(payload)).json()
```

- [ ] **Step 4: Run the tests**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_client`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/client.py crm/integrations/acumatica/test_client.py
git commit -m "feat: Acumatica REST client with OAuth, paging and PUT-upsert"
```

---

### Task 3: Identity custom fields on CRM records

**Files:**
- Modify: `crm/integrations/acumatica/install.py` (replace the Task-1 stub)
- Create: `crm/patches/v1_0/create_custom_fields_for_acumatica_in_crm.py`
- Modify: `crm/patches.txt` (append one line at the end)
- Test: extend `crm/fcrm/doctype/crm_acumatica_settings/test_crm_acumatica_settings.py`

**Interfaces:**
- Consumes: `CRM Acumatica Settings` (Task 1).
- Produces: custom fields `acumatica_noteid` (Data, hidden) and `acumatica_id` (Data, read_only) on **CRM Organization**, **Contact**, **CRM Product**; `acumatica_customer` (Data, read_only) on **CRM Deal**. `ensure_custom_fields()` becomes idempotent-real. Later tasks read/write `doc.acumatica_noteid`.

- [ ] **Step 1: Write the failing test** (append to the Task 1 test class)

```python
	def test_ensure_custom_fields_creates_identity_fields(self):
		from crm.integrations.acumatica.install import ensure_custom_fields

		ensure_custom_fields()
		for doctype in ("CRM Organization", "Contact", "CRM Product"):
			meta = frappe.get_meta(doctype)
			self.assertIsNotNone(meta.get_field("acumatica_noteid"), doctype)
			self.assertIsNotNone(meta.get_field("acumatica_id"), doctype)
		self.assertIsNotNone(frappe.get_meta("CRM Deal").get_field("acumatica_customer"))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.fcrm.doctype.crm_acumatica_settings.test_crm_acumatica_settings`
Expected: the new test FAILS (stub does nothing → fields missing); the four Task-1 tests still pass.

- [ ] **Step 3: Implement**

```python
# crm/integrations/acumatica/install.py
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def _identity_fields(insert_after):
	return [
		{
			"fieldname": "acumatica_noteid",
			"fieldtype": "Data",
			"label": "Acumatica NoteID",
			"hidden": 1,
			"search_index": 1,
			"insert_after": insert_after,
		},
		{
			"fieldname": "acumatica_id",
			"fieldtype": "Data",
			"label": "Acumatica ID",
			"read_only": 1,
			"insert_after": "acumatica_noteid",
		},
	]


def ensure_custom_fields() -> None:
	"""Identity fields the sync keys on. NoteID is Acumatica's rename-stable GUID;
	the human-readable ID is display only. Idempotent -- create_custom_fields
	skips fields that already exist."""
	create_custom_fields(
		{
			"CRM Organization": _identity_fields("organization_name"),
			"Contact": _identity_fields("company_name"),
			"CRM Product": _identity_fields("product_code"),
			"CRM Deal": [
				{
					"fieldname": "acumatica_customer",
					"fieldtype": "Data",
					"label": "Customer in Acumatica",
					"read_only": 1,
					"insert_after": "organization",
				}
			],
		},
		ignore_validate=True,
	)
```

```python
# crm/patches/v1_0/create_custom_fields_for_acumatica_in_crm.py
import frappe


def execute():
	if frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		from crm.integrations.acumatica.install import ensure_custom_fields

		ensure_custom_fields()
```

Append to `crm/patches.txt` (last line): `crm.patches.v1_0.create_custom_fields_for_acumatica_in_crm`

- [ ] **Step 4: Run the tests**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.fcrm.doctype.crm_acumatica_settings.test_crm_acumatica_settings`
Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/install.py crm/patches/v1_0/create_custom_fields_for_acumatica_in_crm.py crm/patches.txt crm/fcrm/doctype/crm_acumatica_settings/test_crm_acumatica_settings.py
git commit -m "feat: Acumatica identity custom fields keyed on NoteID"
```

---

### Task 4: Importer — backfill + incremental sweep (Acumatica → Vectora)

**Files:**
- Create: `crm/integrations/acumatica/importer.py`
- Test: `crm/integrations/acumatica/test_importer.py`

**Interfaces:**
- Consumes: `AcumaticaClient`, `v` (Task 2); `get_settings`, `record_sync_issue` (Task 1); custom fields (Task 3).
- Produces:
  - `upsert_organization(rec: dict) -> str` — returns CRM Organization name.
  - `upsert_contact(rec: dict) -> str | None` — returns Contact name; `None` when the record has no usable name.
  - `upsert_product(rec: dict) -> str` — returns CRM Product name.
  - `run_backfill() -> dict` — full import, returns `{"customers": n, "contacts": n, "products": n, "issues": n}`; sets `last_synced_at` on completion.
  - `nightly_sweep() -> None` — scheduler entry (wired in Task 5): incremental `run_backfill` filtered on `LastModifiedDateTime gt datetimeoffset'{last_synced_at}Z'`; no-op when the integration is disabled.

Field mappings (deliberately minimal and honest — extend later, don't guess):

| Acumatica `Customer` | CRM Organization |
|---|---|
| `NoteID` | `acumatica_noteid` (match key) |
| `CustomerID` | `acumatica_id` |
| `CustomerName` | `organization_name` |
| `CurrencyID` | `currency` (only if that Currency exists locally) |

| Acumatica `Contact` | Contact |
|---|---|
| `NoteID` | `acumatica_noteid` (match key) |
| `ContactID` | `acumatica_id` |
| `FirstName` / `LastName` / `DisplayName` | `first_name` / `last_name` (DisplayName is the fallback first_name) |
| `Email` | row in `email_ids` (is_primary=1) |
| `Phone1` | row in `phone_nos` |
| `BusinessAccount` | `company_name` → the CRM Organization whose `acumatica_id` matches |

| Acumatica `StockItem` | CRM Product |
|---|---|
| `NoteID` | `acumatica_noteid` (match key) |
| `InventoryID` | `product_code` and `acumatica_id` |
| `Description` | `product_name` |
| `DefaultPrice` | `standard_rate` |

- [ ] **Step 1: Write the failing tests**

```python
# crm/integrations/acumatica/test_importer.py
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import importer


def C(**kw):
	"""Build a wrapped Acumatica record from plain values."""
	return {k: {"value": v} for k, v in kw.items()}


class TestUpserts(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_upsert_organization_creates_then_updates(self):
		rec = C(NoteID="guid-org-1", CustomerID="ACME01", CustomerName="Acme Ltd")
		name = importer.upsert_organization(rec)
		org = frappe.get_doc("CRM Organization", name)
		self.assertEqual(org.organization_name, "Acme Ltd")
		self.assertEqual(org.acumatica_id, "ACME01")

		rec2 = C(NoteID="guid-org-1", CustomerID="ACME01", CustomerName="Acme Limited")
		name2 = importer.upsert_organization(rec2)
		self.assertEqual(name, name2)  # matched on NoteID, not created twice
		self.assertEqual(
			frappe.db.get_value("CRM Organization", name, "organization_name"),
			"Acme Limited",
		)

	def test_upsert_contact_links_organization(self):
		importer.upsert_organization(C(NoteID="g-o2", CustomerID="ORG2", CustomerName="Org Two"))
		name = importer.upsert_contact(
			C(NoteID="g-c1", ContactID="7", FirstName="Ana", LastName="Diaz",
			  Email="ana@example.com", BusinessAccount="ORG2")
		)
		contact = frappe.get_doc("Contact", name)
		self.assertEqual(contact.first_name, "Ana")
		self.assertEqual(contact.email_ids[0].email_id, "ana@example.com")
		org_name = frappe.db.get_value("CRM Organization", {"acumatica_id": "ORG2"}, "name")
		self.assertEqual(contact.company_name, org_name)

	def test_upsert_contact_without_name_returns_none(self):
		self.assertIsNone(importer.upsert_contact(C(NoteID="g-c9", ContactID="9")))

	def test_upsert_product_maps_price(self):
		name = importer.upsert_product(
			C(NoteID="g-i1", InventoryID="WIDGET", Description="A widget", DefaultPrice=12.5)
		)
		prod = frappe.get_doc("CRM Product", name)
		self.assertEqual(prod.product_code, "WIDGET")
		self.assertEqual(prod.standard_rate, 12.5)


class TestBackfill(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_run_backfill_counts_and_records_issue_on_bad_record(self, ClientCls):
		client = MagicMock()
		ClientCls.return_value = client

		def fake_iter(entity, **kw):
			if entity == "Customer":
				return iter([C(NoteID="g1", CustomerID="A1", CustomerName="One"),
				             C(NoteID=None, CustomerID="BAD")])  # no NoteID -> issue
			if entity == "Contact":
				return iter([])
			if entity == "StockItem":
				return iter([C(NoteID="g2", InventoryID="X", Description="X", DefaultPrice=1)])
			raise AssertionError(entity)

		client.iter_all.side_effect = fake_iter
		out = importer.run_backfill()
		self.assertEqual(out["customers"], 1)
		self.assertEqual(out["products"], 1)
		self.assertEqual(out["issues"], 1)
		self.assertIsNotNone(
			frappe.db.get_single_value("CRM Acumatica Settings", "last_synced_at")
		)

	def test_nightly_sweep_noop_when_disabled(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")  # get_settings() is cached
		importer.nightly_sweep()  # must not raise, must not call out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_importer`
Expected: `ImportError` — `importer.py` doesn't exist.

- [ ] **Step 3: Implement the importer**

```python
# crm/integrations/acumatica/importer.py
import frappe
from frappe.utils import now_datetime

from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
	get_settings,
	record_sync_issue,
)
from crm.integrations.acumatica.client import AcumaticaClient, v

COMMIT_EVERY = 50  # keep transactions short; a 50k-customer backfill must not hold one tx


def _find_by_noteid(doctype, noteid):
	return frappe.db.get_value(doctype, {"acumatica_noteid": noteid}, "name")


def upsert_organization(rec) -> str:
	noteid = v(rec, "NoteID")
	name = _find_by_noteid("CRM Organization", noteid)
	doc = (
		frappe.get_doc("CRM Organization", name)
		if name
		else frappe.new_doc("CRM Organization")
	)
	doc.organization_name = v(rec, "CustomerName") or v(rec, "CustomerID")
	doc.acumatica_noteid = noteid
	doc.acumatica_id = v(rec, "CustomerID")
	currency = v(rec, "CurrencyID")
	if currency and frappe.db.exists("Currency", currency):
		doc.currency = currency
	doc.save(ignore_permissions=True)
	return doc.name


def upsert_contact(rec) -> str | None:
	first = v(rec, "FirstName") or v(rec, "DisplayName")
	if not first:
		return None
	noteid = v(rec, "NoteID")
	name = _find_by_noteid("Contact", noteid)
	doc = frappe.get_doc("Contact", name) if name else frappe.new_doc("Contact")
	doc.first_name = first
	doc.last_name = v(rec, "LastName") or ""
	doc.acumatica_noteid = noteid
	doc.acumatica_id = v(rec, "ContactID")

	email = v(rec, "Email")
	if email and not any(row.email_id == email for row in doc.email_ids):
		doc.append("email_ids", {"email_id": email, "is_primary": not doc.email_ids})
	phone = v(rec, "Phone1")
	if phone and not any(row.phone == phone for row in doc.phone_nos):
		doc.append("phone_nos", {"phone": phone})

	account = v(rec, "BusinessAccount")
	if account:
		org = frappe.db.get_value("CRM Organization", {"acumatica_id": account}, "name")
		if org:
			doc.company_name = org
	doc.save(ignore_permissions=True)
	return doc.name


def upsert_product(rec) -> str:
	noteid = v(rec, "NoteID")
	name = _find_by_noteid("CRM Product", noteid)
	doc = frappe.get_doc("CRM Product", name) if name else frappe.new_doc("CRM Product")
	doc.product_code = v(rec, "InventoryID")
	doc.product_name = v(rec, "Description") or v(rec, "InventoryID")
	doc.standard_rate = v(rec, "DefaultPrice") or 0
	doc.acumatica_noteid = noteid
	doc.acumatica_id = v(rec, "InventoryID")
	doc.save(ignore_permissions=True)
	return doc.name


_ENTITIES = (
	# (entity, upsert fn key, result counter) -- customers first so contacts can link
	("Customer", upsert_organization, "customers"),
	("Contact", upsert_contact, "contacts"),
	("StockItem", upsert_product, "products"),
)


def run_backfill(modified_since: str | None = None) -> dict:
	"""Import everything (or everything modified since the high-water mark).
	Records that fail land in the sync-issues table instead of aborting the run."""
	settings = get_settings()
	client = AcumaticaClient(settings)
	counts = {"customers": 0, "contacts": 0, "products": 0, "issues": 0}
	filter_ = None
	if modified_since:
		# OData v3 literal; the trailing Z matters -- Acumatica stores UTC
		filter_ = f"LastModifiedDateTime gt datetimeoffset'{modified_since}Z'"

	started_at = now_datetime()
	for entity, upsert, counter in _ENTITIES:
		done_in_entity = 0
		for rec in client.iter_all(entity, filter=filter_):
			try:
				if not v(rec, "NoteID"):
					raise ValueError("record has no NoteID")
				if upsert(rec) is not None:
					counts[counter] += 1
			except Exception as e:
				counts["issues"] += 1
				record_sync_issue(
					entity, v(rec, "CustomerID") or v(rec, "InventoryID") or v(rec, "ContactID") or "?",
					"Import Failed", str(e),
				)
			done_in_entity += 1
			if done_in_entity % COMMIT_EVERY == 0:
				frappe.db.commit()
		frappe.db.commit()

	# High-water mark is when this run STARTED: anything modified mid-run is
	# picked up again next sweep rather than lost in the gap.
	frappe.db.set_single_value(
		"CRM Acumatica Settings", "last_synced_at", started_at
	)
	frappe.db.commit()
	return counts


def nightly_sweep() -> None:
	"""Scheduler entry. Webhooks are the latency mechanism; this is the
	correctness mechanism -- Acumatica keeps failed push notifications for
	only 2 days, so the sweep must always run."""
	settings = get_settings()
	if not settings.enabled:
		return
	since = settings.last_synced_at
	run_backfill(modified_since=str(since).replace(" ", "T") if since else None)
```

- [ ] **Step 4: Run the tests**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_importer`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/importer.py crm/integrations/acumatica/test_importer.py
git commit -m "feat: Acumatica backfill importer with NoteID upserts and sweep"
```

---

### Task 5: Wire the sweep and the backfill entry point

**Files:**
- Modify: `crm/hooks.py` (scheduler_events, `daily_long` list — currently lines ~265-270, the list containing `crm.lead_syncing.background_sync.sync_leads_from_sources_daily`)
- Create: `crm/integrations/acumatica/api.py`
- Test: `crm/integrations/acumatica/test_api.py`

**Interfaces:**
- Consumes: `run_backfill`, `nightly_sweep` (Task 4).
- Produces: `crm.integrations.acumatica.importer.nightly_sweep` registered in `daily_long`; whitelisted `crm.integrations.acumatica.api.start_backfill()` (System Manager / Sales Manager only) that enqueues `run_backfill` on the **long** queue and returns `{"queued": True}`; whitelisted `crm.integrations.acumatica.api.get_sync_status()` returning `{"last_synced_at": ..., "open_issues": n}` for the settings page (Task 8).

- [ ] **Step 1: Write the failing tests**

```python
# crm/integrations/acumatica/test_api.py
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestHookWiring(FrappeTestCase):
	def test_sweep_is_registered_daily_long(self):
		from crm import hooks

		self.assertIn(
			"crm.integrations.acumatica.importer.nightly_sweep",
			hooks.scheduler_events["daily_long"],
		)

	def test_registered_methods_are_importable(self):
		frappe.get_attr("crm.integrations.acumatica.importer.nightly_sweep")
		frappe.get_attr("crm.integrations.acumatica.api.start_backfill")
		frappe.get_attr("crm.integrations.acumatica.api.get_sync_status")


class TestStartBackfill(FrappeTestCase):
	@patch("crm.integrations.acumatica.api.frappe.enqueue")
	def test_start_backfill_enqueues_on_long_queue(self, enqueue):
		frappe.set_user("Administrator")
		from crm.integrations.acumatica.api import start_backfill

		out = start_backfill()
		self.assertTrue(out["queued"])
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")

	def test_start_backfill_rejects_non_managers(self):
		from crm.integrations.acumatica.api import start_backfill

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				start_backfill()
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_api`
Expected: FAIL — hook not registered, `api.py` missing.

- [ ] **Step 3: Implement**

In `crm/hooks.py`, append to the `daily_long` list:

```python
	"daily_long": [
		"crm.lead_syncing.background_sync.sync_leads_from_sources_daily",
		# off unless an admin turns scheduled_reenrichment on; long because each
		# record it queues is a crawl of somebody else's website
		"crm.domain_enrichment.tasks.reenrich_stale_records",
		# correctness sweep for the Acumatica integration -- webhooks only lower
		# latency, they do not guarantee delivery (2-day retention on their side)
		"crm.integrations.acumatica.importer.nightly_sweep",
	],
```

```python
# crm/integrations/acumatica/api.py
import frappe
from frappe import _


@frappe.whitelist()
def start_backfill() -> dict:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	if not settings.enabled:
		frappe.throw(_("Enable the Acumatica integration first"))
	frappe.enqueue(
		"crm.integrations.acumatica.importer.run_backfill",
		queue="long",
		job_id="acumatica_backfill",
		deduplicate=True,
	)
	return {"queued": True}


@frappe.whitelist()
def get_sync_status() -> dict:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	open_issues = sum(1 for row in settings.sync_issues if not row.dismissed)
	return {"last_synced_at": settings.last_synced_at, "open_issues": open_issues}
```

- [ ] **Step 4: Run the tests**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_api`
Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add crm/hooks.py crm/integrations/acumatica/api.py crm/integrations/acumatica/test_api.py
git commit -m "feat: Acumatica sweep on the scheduler and a queued backfill entry point"
```

---

### Task 6: Outbound — customer on deal status, sales quote from deal

**Files:**
- Create: `crm/integrations/acumatica/outbound.py`
- Modify: `crm/hooks.py` (`doc_events` → `"CRM Deal"` → `"on_update"` list, beside `crm.fcrm.doctype.erpnext_crm_settings.erpnext_crm_settings.create_customer_in_erpnext`)
- Test: `crm/integrations/acumatica/test_outbound.py`

**Interfaces:**
- Consumes: `AcumaticaClient.put`, `v` (Task 2); `get_settings`, `record_sync_issue` (Task 1); `acumatica_*` custom fields (Task 3).
- Produces:
  - `create_customer_in_acumatica(doc, method)` — doc-event handler on CRM Deal `on_update`; no-op unless enabled + `create_customer_on_status_change` + status matches `deal_status`; PUTs a `Customer`, stores returned `CustomerID` on `deal.acumatica_customer` and NoteID/ID on the deal's organization.
  - `create_sales_quote_from_deal(crm_deal: str) -> str` — whitelisted; PUTs a `SalesOrder` with `OrderType = settings.quote_order_type`, one detail line per deal product; returns the created order's `OrderNbr`.

- [ ] **Step 1: Write the failing tests**

```python
# crm/integrations/acumatica/test_outbound.py
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import outbound


def _wrapped(**kw):
	return {k: {"value": v} for k, v in kw.items()}


def _enable(**overrides):
	s = frappe.get_doc("CRM Acumatica Settings")
	s.enabled = 1
	s.instance_url = "https://t.acumatica.com"
	s.create_customer_on_status_change = overrides.get("create_customer_on_status_change", 1)
	s.deal_status = overrides.get("deal_status", "Won")
	s.quote_order_type = "QT"
	s.save(ignore_permissions=True)
	frappe.clear_cache(doctype="CRM Acumatica Settings")


def _make_deal(status="Won"):
	org = frappe.get_doc(
		{"doctype": "CRM Organization", "organization_name": f"Out-{frappe.generate_hash(length=6)}"}
	).insert(ignore_permissions=True)
	deal = frappe.get_doc(
		{"doctype": "CRM Deal", "organization": org.name, "status": status}
	).insert(ignore_permissions=True)
	return org, deal


class TestCreateCustomer(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_noop_when_disabled(self, ClientCls):
		org, deal = _make_deal()
		outbound.create_customer_in_acumatica(deal, "on_update")
		ClientCls.assert_not_called()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_puts_customer_and_stores_ids(self, ClientCls):
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(CustomerID="NEW01", NoteID="g-new")
		org, deal = _make_deal(status="Won")
		outbound.create_customer_in_acumatica(deal, "on_update")
		entity, payload = client.put.call_args[0]
		self.assertEqual(entity, "Customer")
		self.assertEqual(payload["CustomerName"], org.organization_name)
		self.assertEqual(
			frappe.db.get_value("CRM Deal", deal.name, "acumatica_customer"), "NEW01"
		)
		self.assertEqual(
			frappe.db.get_value("CRM Organization", org.name, "acumatica_noteid"), "g-new"
		)

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_skips_when_org_already_linked(self, ClientCls):
		_enable()
		org, deal = _make_deal(status="Won")
		frappe.db.set_value("CRM Organization", org.name, "acumatica_noteid", "g-existing")
		client = MagicMock()
		ClientCls.return_value = client
		outbound.create_customer_in_acumatica(deal, "on_update")
		client.put.assert_not_called()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_failure_lands_in_sync_issues_not_exception(self, ClientCls):
		from crm.integrations.acumatica.client import AcumaticaError

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = AcumaticaError("boom", status_code=422)
		org, deal = _make_deal(status="Won")
		outbound.create_customer_in_acumatica(deal, "on_update")  # must not raise
		issues = frappe.get_doc("CRM Acumatica Settings").sync_issues
		self.assertTrue(any(i.kind == "Push Failed" for i in issues))


class TestHook(FrappeTestCase):
	def test_handler_registered_on_deal_update(self):
		from crm import hooks

		self.assertIn(
			"crm.integrations.acumatica.outbound.create_customer_in_acumatica",
			hooks.doc_events["CRM Deal"]["on_update"],
		)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_outbound`
Expected: `ImportError` — `outbound.py` missing.

- [ ] **Step 3: Implement**

```python
# crm/integrations/acumatica/outbound.py
import frappe
from frappe import _

from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
	get_settings,
	record_sync_issue,
)
from crm.integrations.acumatica.client import AcumaticaClient, AcumaticaError, v


def create_customer_in_acumatica(doc, method):
	"""CRM Deal on_update handler. Mirrors the ERPNext integration's trigger shape:
	fires once when the deal reaches the configured status."""
	settings = get_settings()
	if (
		not settings.enabled
		or not settings.create_customer_on_status_change
		or doc.status != settings.deal_status
		or not doc.organization
	):
		return

	org = frappe.get_doc("CRM Organization", doc.organization)
	if org.get("acumatica_noteid"):
		# already linked -- record the link on the deal and stop
		if not doc.get("acumatica_customer"):
			frappe.db.set_value(
				"CRM Deal", doc.name, "acumatica_customer", org.get("acumatica_id")
			)
		return

	payload = {"CustomerName": org.organization_name}
	if settings.customer_numbering == "From Organization Name":
		payload["CustomerID"] = org.organization_name[:30].upper().replace(" ", "")

	try:
		created = AcumaticaClient(settings).put("Customer", payload)
	except AcumaticaError as e:
		record_sync_issue("Customer", org.name, "Push Failed", f"{e} :: {e.body}")
		return

	frappe.db.set_value(
		"CRM Organization",
		org.name,
		{"acumatica_noteid": v(created, "NoteID"), "acumatica_id": v(created, "CustomerID")},
	)
	frappe.db.set_value("CRM Deal", doc.name, "acumatica_customer", v(created, "CustomerID"))


@frappe.whitelist()
def create_sales_quote_from_deal(crm_deal: str) -> str:
	frappe.has_permission("CRM Deal", "write", doc=crm_deal, throw=True)
	settings = get_settings()
	if not settings.enabled:
		frappe.throw(_("The Acumatica integration is not enabled"))

	deal = frappe.get_doc("CRM Deal", crm_deal)
	customer_id = deal.get("acumatica_customer") or frappe.db.get_value(
		"CRM Organization", deal.organization, "acumatica_id"
	)
	if not customer_id:
		frappe.throw(
			_("This deal's organization is not linked to an Acumatica customer yet")
		)

	details = []
	# CRM Deal's child table is `products` (CRM Products rows); the row's link to
	# the CRM Product is `product_code`, the quantity field is `qty`.
	for row in deal.get("products") or []:
		inventory_id = frappe.db.get_value("CRM Product", row.product_code, "acumatica_id")
		if not inventory_id:
			continue
		details.append({"InventoryID": inventory_id, "OrderQty": row.qty or 1})

	payload = {
		"OrderType": settings.quote_order_type,
		"CustomerID": customer_id,
		"Description": f"Vectora deal {deal.name}",
	}
	if details:
		payload["Details"] = details

	created = AcumaticaClient(settings).put("SalesOrder", payload)
	return v(created, "OrderNbr") or ""
```

In `crm/hooks.py`, the `"CRM Deal"` `doc_events` entry gains one line in its `on_update` list, directly after `create_customer_in_erpnext`:

```python
			"crm.integrations.acumatica.outbound.create_customer_in_acumatica",
```

- [ ] **Step 4: Run the tests**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_outbound`
Expected: all 6 PASS. Note: if `_make_deal` fails because `CRM Deal.status` "Won" doesn't exist on test_site, read the available statuses with `frappe.get_all("CRM Deal Status", pluck="name")` and use the first — adjust `_enable(deal_status=...)` accordingly; the tests must not invent fixtures the site lacks.

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/outbound.py crm/integrations/acumatica/test_outbound.py crm/hooks.py
git commit -m "feat: push customers and sales quotes from deals into Acumatica"
```

---

### Task 7: Webhook receiver (latency upgrade)

**Files:**
- Create: `crm/integrations/acumatica/webhook.py`
- Test: `crm/integrations/acumatica/test_webhook.py`

**Interfaces:**
- Consumes: `get_settings` (Task 1); `run_backfill` (Task 4).
- Produces: `crm.integrations.acumatica.webhook.handle_notification` — guest-whitelisted POST endpoint. URL the operator pastes into Acumatica's Push Notifications (SM302000) webhook destination: `https://<site>/api/method/crm.integrations.acumatica.webhook.handle_notification?key=<webhook_verify_token>`. On a valid call it enqueues an incremental sweep (short debounce via `job_id` dedup) and returns `{"ok": True}` — Acumatica needs a 20x or it counts the delivery as failed.

Verification follows the Exotel pattern (`crm/integrations/exotel/handler.py:213-220`): compare `frappe.request.args.get("key")` against the stored token with `hmac.compare_digest`; missing/empty token on either side → 401. The payload is not trusted or parsed for data — it only *triggers* a pull through the authenticated client, so a forged request can cause nothing but a redundant sweep.

- [ ] **Step 1: Write the failing tests**

```python
# crm/integrations/acumatica/test_webhook.py
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import webhook


class TestWebhook(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "webhook_verify_token", "tok123")
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def tearDown(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def _call(self, key):
		req = MagicMock()
		req.args = {"key": key} if key is not None else {}
		with patch.object(frappe.local, "request", req, create=True):
			return webhook.handle_notification()

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_valid_key_enqueues_sweep(self, enqueue):
		out = self._call("tok123")
		self.assertTrue(out["ok"])
		self.assertEqual(
			enqueue.call_args[0][0], "crm.integrations.acumatica.importer.nightly_sweep"
		)

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_wrong_key_401s(self, enqueue):
		with self.assertRaises(frappe.PermissionError):
			self._call("wrong")
		enqueue.assert_not_called()

	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_missing_stored_token_401s_even_with_matching_empty(self, enqueue):
		frappe.db.set_single_value("CRM Acumatica Settings", "webhook_verify_token", "")
		frappe.clear_cache(doctype="CRM Acumatica Settings")
		with self.assertRaises(frappe.PermissionError):
			self._call("")
		enqueue.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_webhook`
Expected: `ImportError` — `webhook.py` missing.

- [ ] **Step 3: Implement**

```python
# crm/integrations/acumatica/webhook.py
import hmac

import frappe

# Paste into Acumatica's Push Notifications (SM302000) webhook destination:
# https://<site>/api/method/crm.integrations.acumatica.webhook.handle_notification?key=<webhook_verify_token>
# The payload is deliberately ignored: this endpoint only triggers a pull
# through the authenticated client, so its worst-case abuse is a redundant sweep.


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def handle_notification():
	key = frappe.request.args.get("key") if frappe.request else None
	stored = frappe.db.get_single_value("CRM Acumatica Settings", "webhook_verify_token")
	if not (key and stored and hmac.compare_digest(key, stored)):
		frappe.throw("Invalid webhook key", frappe.PermissionError)

	if frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		frappe.enqueue(
			"crm.integrations.acumatica.importer.nightly_sweep",
			queue="long",
			job_id="acumatica_webhook_sweep",
			deduplicate=True,  # a burst of notifications collapses to one sweep
		)
	return {"ok": True}
```

- [ ] **Step 4: Run the tests**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_webhook`
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add crm/integrations/acumatica/webhook.py crm/integrations/acumatica/test_webhook.py
git commit -m "feat: Acumatica push-notification receiver that debounces into a sweep"
```

---

### Task 8: Settings page + deal button (frontend)

**Files:**
- Create: `frontend/src/components/Settings/AcumaticaSettings.vue`
- Modify: `frontend/src/components/Settings/Settings.vue` (integrations items array, directly after the SIMERP entry — see the block containing `label: __('SIMERP')`)
- Modify: `crm/integrations/acumatica/api.py` (add `get_crm_form_script`)
- Test: `crm/integrations/acumatica/test_api.py` (extend)

**Interfaces:**
- Consumes: `start_backfill`, `get_sync_status` (Task 5); `create_sales_quote_from_deal` (Task 6); `CRM Acumatica Settings` doc via `createDocumentResource`.
- Produces: a Settings → Integrations → "Acumatica" page (managers only) with: enable toggle, connection fields, Save, "Run backfill" button, last-synced timestamp + open-issue count; `get_crm_form_script()` returning a Form Script string that adds a **Create Sales Quote** action on deals when the integration is enabled.

No new pure logic lands in `frontend/src/utils/`, so no frontend unit tests are added — the page is declarative resource wiring, same as `ERPNextSettings.vue`. The python-side form script IS tested.

- [ ] **Step 1: Write the failing test** (append to `crm/integrations/acumatica/test_api.py`)

```python
class TestFormScript(FrappeTestCase):
	def test_form_script_mentions_quote_action_and_endpoint(self):
		from crm.integrations.acumatica.api import get_crm_form_script

		script = get_crm_form_script()
		self.assertIn("Create Sales Quote", script)
		self.assertIn("crm.integrations.acumatica.outbound.create_sales_quote_from_deal", script)
		self.assertIn("CRM Acumatica Settings", script)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_api`
Expected: new test FAILS (`get_crm_form_script` missing); earlier tests still pass.

- [ ] **Step 3: Implement backend + frontend**

Append to `crm/integrations/acumatica/api.py`:

```python
@frappe.whitelist()
def get_crm_form_script():
	"""Form Script for CRM Deal -- same delivery mechanism as the ERPNext
	integration's get_crm_form_script. Additive only: it registers an action,
	it does not touch existing helpers."""
	return """class CRMDeal {
	onLoad() {
		if (this.doc.__newDocument) return
		call("frappe.client.get_single_value", {
			doctype: "CRM Acumatica Settings",
			field: "enabled",
		}).then((enabled) => {
			if (enabled) this.doc.trigger("setAcumaticaActions")
		})
	}
	setAcumaticaActions() {
		this.actions.push({
			label: __("Create Sales Quote"),
			onClick: () => {
				call("crm.integrations.acumatica.outbound.create_sales_quote_from_deal", {
					crm_deal: this.doc.name,
				}).then((order_nbr) => {
					frappe.show_alert({ message: __("Sales quote {0} created in Acumatica", [order_nbr]), indicator: "green" })
				})
			},
		})
	}
}"""
```

`frontend/src/components/Settings/AcumaticaSettings.vue` — model on `ERPNextSettings.vue` but flat and small. Full component:

```vue
<template>
  <div class="flex h-full flex-col gap-6 p-8 overflow-y-auto">
    <div class="flex justify-between">
      <h2 class="text-xl font-semibold text-ink-gray-8">
        {{ __('Acumatica Settings') }}
      </h2>
      <Switch
        v-if="settings.doc"
        v-model="settings.doc.enabled"
        :label="settings.doc.enabled ? __('Enabled') : __('Disabled')"
      />
    </div>

    <template v-if="settings.doc">
      <div class="grid grid-cols-2 gap-4">
        <FormControl v-model="settings.doc.instance_url" :label="__('Instance URL')" placeholder="https://tenant.acumatica.com" />
        <FormControl v-model="settings.doc.endpoint_version" :label="__('Endpoint Version')" />
        <FormControl v-model="settings.doc.client_id" :label="__('Client ID')" />
        <FormControl v-model="settings.doc.client_secret" type="password" :label="__('Client Secret')" />
        <FormControl v-model="settings.doc.username" :label="__('API Username')" />
        <FormControl v-model="settings.doc.password" type="password" :label="__('API Password')" />
        <FormControl v-model="settings.doc.quote_order_type" :label="__('Quote Order Type')" />
        <FormControl v-model="settings.doc.webhook_verify_token" :label="__('Webhook Verify Token')" />
      </div>

      <div class="flex items-center gap-3">
        <Button :label="__('Save')" variant="solid" :loading="settings.save.loading" @click="settings.save.submit()" />
        <Button :label="__('Run backfill')" :disabled="!settings.doc.enabled" @click="runBackfill" />
      </div>

      <div v-if="status" class="text-p-sm text-ink-gray-6">
        {{ __('Last synced') }}: {{ status.last_synced_at || __('never') }}
        · {{ __('Open sync issues') }}: {{ status.open_issues }}
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { createDocumentResource, call, FormControl, Button, Switch, toast } from 'frappe-ui'

const settings = createDocumentResource({
  doctype: 'CRM Acumatica Settings',
  name: 'CRM Acumatica Settings',
  auto: true,
})

const status = ref(null)

async function loadStatus() {
  status.value = await call('crm.integrations.acumatica.api.get_sync_status')
}

async function runBackfill() {
  await call('crm.integrations.acumatica.api.start_backfill')
  toast.success(__('Backfill queued — watch Last synced below'))
  loadStatus()
}

onMounted(loadStatus)
</script>
```

`frontend/src/components/Settings/Settings.vue` — add after the SIMERP entry (import `AcumaticaSettings` beside the other settings imports; reuse `ERPNextIcon` until a dedicated icon exists):

```javascript
        {
          label: __('Acumatica'),
          icon: ERPNextIcon,
          component: markRaw(AcumaticaSettings),
          condition: () => isManager(),
        },
```

- [ ] **Step 4: Run tests + lint**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --module crm.integrations.acumatica.test_api`
Expected: all 5 PASS.
Run: `cd /workspace/frontend && yarn test:run`
Expected: suite green (no new frontend tests; nothing existing broken).
Run: `pre-commit run --files frontend/src/components/Settings/AcumaticaSettings.vue frontend/src/components/Settings/Settings.vue crm/integrations/acumatica/api.py`
Expected: pass (re-add if prettier rewrites).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Settings/AcumaticaSettings.vue frontend/src/components/Settings/Settings.vue crm/integrations/acumatica/api.py crm/integrations/acumatica/test_api.py
git commit -m "feat: Acumatica settings page and Create Sales Quote deal action"
```

---

### Task 9: Docs + full-suite gate

**Files:**
- Create: `.pi/feats/acumatica/README.md`
- Modify: `AGENTS.md` (the "Where to read before working" table)
- Test: none new — this task's gate is the full suites.

**Interfaces:** none — documentation and verification only.

- [ ] **Step 1: Write the feature doc**

`.pi/feats/acumatica/README.md`:

```markdown
# Acumatica integration

Two-way sync with a client's Acumatica ERP. One ERP per deployment: enabling
this integration requires the SIMERP (ERPNext) integration to be disabled, and
vice versa — enforced in `CRM Acumatica Settings.validate`.

## Ownership model

| Entity | System of record | Direction |
|---|---|---|
| Customers, Contacts, Stock Items | Acumatica | pulled in (backfill + nightly sweep + webhook) |
| Leads, Deals | Vectora | deal events push out |
| Sales quotes | Acumatica | created from a deal via the **Create Sales Quote** action |

Identity is Acumatica's `NoteID` GUID (`acumatica_noteid` custom field);
`acumatica_id` holds the human-readable key for display. All remote writes are
PUT-upserts — Acumatica has no create verb; key fields in the body decide
create-vs-update, which is why writes key on NoteID.

## Moving parts

- `crm/integrations/acumatica/client.py` — OAuth password grant against
  `{instance}/identity/connect/token`, token cached with TTL, one re-auth retry
  on 401. Field values are wrapped `{"value": x}` — use `v()`/`wrap()`.
- `importer.py` — `run_backfill()` (full or `LastModifiedDateTime`-filtered),
  commits every 50 records, failures land in the settings' sync-issues table.
  High-water mark = run *start* time, so mid-run edits are re-swept, not lost.
- `outbound.py` — customer-on-deal-status (mirrors the ERPNext trigger shape)
  and `create_sales_quote_from_deal`.
- `webhook.py` — receiver for Acumatica Push Notifications (SM302000). The
  webhook only *triggers* a pull; the payload is ignored. **The nightly sweep is
  the correctness mechanism** — Acumatica retains failed notifications for only
  2 days, so webhooks must never be the only sync path.

## Operational notes

- Acumatica licences cap API request rates; `request_pause` throttles paging.
  Check the client's licence tier before promising a backfill timeline.
- `endpoint_version` differs per instance (default `24.200.001`); a 404 on the
  entity URL usually means the version, not the entity, is wrong.
- Historical quotations are NOT imported as deals — fabricated deal history
  would poison forecasting, health scoring, and quota analytics.
```

- [ ] **Step 2: Add the AGENTS.md table row**

In the "Where to read before working" table, after the reporting row:

```markdown
| Acumatica ERP sync | [feats/acumatica/README.md](./.pi/feats/acumatica/README.md) |
```

- [ ] **Step 3: Run the full gates**

Run: `cd /workspace/frappe-bench && bench --site test_site run-tests --app crm`
Expected: OK across all categories, 0 failures (skips for erpnext-dependent tests are normal).
Run: `cd /workspace/frontend && yarn test:run`
Expected: green.
Run: `pre-commit run --files $(git diff --name-only develop...HEAD | tr '\n' ' ')`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add .pi/feats/acumatica/README.md AGENTS.md
git commit -m "docs: Acumatica integration feature doc and index entry"
```

- [ ] **Step 5: Open the PR**

```bash
git push -u origin feat/acumatica-integration
gh pr create --base develop --title "feat: two-way Acumatica ERP integration" \
  --body "Backfill + nightly sweep + webhook inbound; customer and sales-quote outbound. One ERP per deployment (mutually exclusive with SIMERP). See .pi/feats/acumatica/README.md for the ownership model."
```

---

## Deferred (deliberately out of scope — do not build speculatively)

- **Contact/Customer edits in Vectora pushed back to Acumatica** — Acumatica is system of record; Vectora-side edits to imported records are currently local-only. Revisit only when a real workflow demands it.
- **Historical quotation import** — read-only references, if ever. Never as deals.
- **Per-entity webhook targeting** — the debounced whole-sweep is O(changed records) anyway thanks to the `LastModifiedDateTime` filter.
- **A provider abstraction over erpnext/acumatica** — explicitly rejected: one ERP per deployment.

## Prerequisites the client must supply (blocking live testing, not implementation)

1. Tenant URL and working endpoint version (Task 1's defaults are a guess until verified).
2. An OAuth connected app (`client_id`/`client_secret`) and an API user with rights to Customer, Contact, StockItem, SalesOrder.
3. The instance's quote order type (default `QT`).
4. Their API licence tier / rate limits — sets `request_pause` and the backfill timeline.
5. (For webhooks) an admin to configure SM302000 with our URL + token.
