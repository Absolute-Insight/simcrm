# Acumatica Integration — Production-Ready Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every finding of the 2026-09-05 Acumatica integration audit so the live sync, the outbound writes and the spreadsheet import can be switched on for a client without a rep, an operator or the client's ERP being surprised.

**Architecture:** The integration stays as it is shaped — `client.py` (HTTP), `importer.py` (inbound upserts + sweep), `outbound.py` (ERP writes), `api.py`/`webhook.py` (entry points), `spreadsheet.py` (one-way file import), one Single doctype for settings with a child table of sync issues, one Vue settings panel. Each task hardens one seam: secrets out of reach of reps, ERP calls off the request thread, failures retried and visible, bulk loads that do not notify, and a UI that can test a connection and show what broke.

**Tech Stack:** Frappe (Python, tabs), frappe-ui/Vue 3, `requests`, RQ. Tests: `bench --site test_site run-tests --module <module>` inside `simcrm_devcontainer-frappe-1` at `/home/frappe/frappe-bench` with `PYTHONPATH=/workspace/.worktrees/<worktree>` prefix so the worktree's code is imported. Ruff: `ruff check` + `ruff format` (CI's pinned ruff enforces `zip(..., strict=True)` and UP038).

**Spec:** the audit in the conversation of 2026-09-05, reproduced as "Findings" below. No separate spec file.

## Global Constraints

- Tabs for indentation in Python (the repo's ruff config). Comments explain *why*, in the voice of the surrounding code.
- Never enable `CRM Acumatica Settings` on the dev or test site outside a test's own try/finally; `tearDown` must leave `enabled = 0`.
- `webhook_verify_token`, `client_secret`, `password` are read only through `doc.get_password(field, raise_exception=False)`; never through `frappe.db.get_single_value`.
- Every new whitelisted method has an explicit permission check on its first line (`frappe.only_for(...)` or `frappe.has_permission(..., throw=True)`).
- Existing tests keep passing; the ones this plan changes are named in the task that changes them. Run the whole Acumatica package after each task: `crm.integrations.acumatica.test_api`, `test_client`, `test_importer`, `test_outbound`, `test_spreadsheet`, `test_webhook`, and `crm.fcrm.doctype.crm_acumatica_settings.test_crm_acumatica_settings`, `crm.fcrm.doctype.crm_product.test_product_item_sync`, `crm.tests.test_organization_api`, `crm.agent.tests.test_analyst_data` (if present).
- One commit per task, conventional prefix (`fix:`, `feat:`, `docs:`, `test:`). Trailer on every commit: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01ABSBq3oroMXLPTSe86saQp`.
- Frontend: `cd frontend && yarn test:run` stays green (no component tests exist; pure utils only). Prettier/eslint run via the PostToolUse hook inside the container.

## Findings (the spec)

1. Sales User can read `webhook_verify_token`, `client_id`, `instance_url` via `frappe.client.get_single_value` (doctype-level read granted so the Deal form script can check `enabled`; `get_single_value` does no field check).
2. `create_customer_in_acumatica` runs HTTP inside the CRM Deal `on_update` hook — up to ~60 s inside a rep's save.
3. Records that fail in a sweep are logged as sync issues and never retried; the high-water mark moves past them.
4. `create_sales_quote_from_deal` silently drops product lines with no `acumatica_id` when at least one line is linked.
5. Backfill (`job_id=acumatica_backfill`), webhook sweep (`acumatica_webhook_sweep`) and the scheduler's `daily_long` sweep (no job id) can run concurrently.
6. `branch` setting is collected and documented but never sent.
7. `CustomerID` derived from the organization name is cut at 30 chars; Acumatica's default segment is 10.
8. No UI for sync issues (`get_open_sync_issues`/`dismiss_sync_issue` have no callers); no connection test; a failed backfill is invisible.
9. `settings.save.submit()` in the Vue panel has no `onError` — refused saves are silent.
10. The webhook key travels only in the query string (`?key=`) and lands in access logs.
11. The spreadsheet import assigns every deal through `assign_to._add`, which always notifies: one ToDo + Notification Log + email per deal, and an RQ job storm that trips `max_queued_jobs`.
12. Live-sync gaps (deletions/inactive not mirrored, no 429 backoff) — document only.

## File map

| File | Change |
|---|---|
| `crm/fcrm/doctype/crm_acumatica_settings/crm_acumatica_settings.json` | `webhook_verify_token` → Password; new fields `customer_id_max_length` (Int, 10), `pending_retries` (JSON, hidden), `last_sync_error` (Small Text, read-only); drop the Sales User permission row |
| `crm/fcrm/doctype/crm_acumatica_settings/crm_acumatica_settings.py` | `set_last_sync_error()`, `get_pending_retries()/set_pending_retries()` helpers |
| `crm/patches/v1_0/encrypt_acumatica_webhook_token.py` + `crm/patches.txt` | move a plaintext token into the encrypted store |
| `crm/integrations/acumatica/api.py` | `is_enabled()` (any logged-in user), `test_connection()`, richer `get_sync_status()`; form script uses `is_enabled` |
| `crm/integrations/acumatica/webhook.py` | header `X-Vectora-Key` first, `?key=` fallback; token via `get_password` |
| `crm/integrations/acumatica/client.py` | `branch` in the token body; `ping()` for the connection test |
| `crm/integrations/acumatica/outbound.py` | hook enqueues; `push_customer_for_deal(deal)` worker; quote refuses unlinked lines; `customer_id_max_length` |
| `crm/integrations/acumatica/importer.py` | one `SYNC_JOB_ID`; `schedule_sweep()`; filelock; retry queue; `last_sync_error` |
| `crm/hooks.py` | `daily_long` → `schedule_sweep`; deal `on_update` → `queue_customer_push` |
| `crm/fcrm/doctype/crm_deal/crm_deal.py` | `assign_agent` honours `frappe.flags.bulk_assign_quietly` |
| `crm/integrations/acumatica/spreadsheet.py` | sets the flag for its run; retries `QueueOverloaded` |
| `frontend/src/components/Settings/AcumaticaSettings.vue` | save `onError`, generate-token button, Test connection, sync issues list + dismiss, backfill state |
| `.pi/feats/acumatica/README.md` | webhook header, retries, connection test, gaps |
| tests | named per task |

---

### Task 1: Secrets out of a rep's reach

**Files:**
- Modify: `crm/fcrm/doctype/crm_acumatica_settings/crm_acumatica_settings.json` (`webhook_verify_token` fieldtype → `Password`; remove the `Sales User` permission row)
- Create: `crm/patches/v1_0/encrypt_acumatica_webhook_token.py`; append `crm.patches.v1_0.encrypt_acumatica_webhook_token` under `[post_model_sync]` in `crm/patches.txt`
- Modify: `crm/integrations/acumatica/api.py` (add `is_enabled`; form script calls it)
- Modify: `crm/integrations/acumatica/webhook.py` (token via `get_password`)
- Modify: `crm/fcrm/doctype/crm_acumatica_settings/test_crm_acumatica_settings.py` (`test_sales_user_can_read_the_enabled_flag` → reads through `is_enabled`; new `test_sales_user_cannot_read_the_settings_document`)
- Modify: `crm/integrations/acumatica/test_webhook.py` (set the token through the doc so it is encrypted)
- Modify: `crm/integrations/acumatica/test_api.py` (`test_form_script_mentions_quote_action_and_endpoint` asserts `crm.integrations.acumatica.api.is_enabled`)

**Interfaces:**
- Produces: `crm.integrations.acumatica.api.is_enabled() -> bool` — whitelisted, no role requirement beyond being logged in (`frappe.session.user != "Guest"`), returns `bool(frappe.db.get_single_value("CRM Acumatica Settings", "enabled"))`.

- [ ] **Step 1: Failing tests.** In `test_crm_acumatica_settings.py` replace `test_sales_user_can_read_the_enabled_flag` with:

```python
	def test_a_sales_user_learns_only_whether_it_is_enabled(self):
		"""The deal form script needs one bit. The settings document also holds the
		webhook secret and the API identity, and frappe.client.get_single_value checks
		doctype-level read only -- so the bit comes through its own method and the
		document itself is closed to reps."""
		from frappe.client import get_single_value

		from crm.integrations.acumatica.api import is_enabled

		email = "acumatica-rep@crmtest.test"
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		frappe.set_user(email)
		try:
			self.assertFalse(is_enabled())
			with self.assertRaises(frappe.PermissionError):
				get_single_value("CRM Acumatica Settings", "webhook_verify_token")
		finally:
			frappe.set_user("Administrator")

	def test_the_webhook_token_is_stored_encrypted(self):
		s = frappe.get_doc("CRM Acumatica Settings")
		s.webhook_verify_token = "plain-token-for-test"
		s.flags.ignore_validate = True
		s.save(ignore_permissions=True)
		try:
			self.assertNotEqual(
				frappe.db.get_single_value("CRM Acumatica Settings", "webhook_verify_token"),
				"plain-token-for-test",
			)
			self.assertEqual(s.get_password("webhook_verify_token"), "plain-token-for-test")
		finally:
			s.webhook_verify_token = ""
			s.save(ignore_permissions=True)
```

In `test_webhook.py`, wherever the token is set with `frappe.db.set_single_value(..., "webhook_verify_token", ...)`, replace with a helper:

```python
def _set_token(value):
	s = frappe.get_doc("CRM Acumatica Settings")
	s.webhook_verify_token = value
	s.flags.ignore_validate = True
	s.save(ignore_permissions=True)
```

and call `_set_token("")` in `tearDown`. In `test_api.py::test_form_script_mentions_quote_action_and_endpoint` add `self.assertIn("crm.integrations.acumatica.api.is_enabled", script)` and `self.assertNotIn("frappe.client.get_single_value", script)`.

- [ ] **Step 2: Run, expect failures** (`is_enabled` missing; token readable; script string).

- [ ] **Step 3: Implement.** JSON: change the `webhook_verify_token` field's `"fieldtype": "Data"` to `"Password"`; delete the permission object whose `"role"` is `"Sales User"`. `api.py`:

```python
@frappe.whitelist()
def is_enabled() -> bool:
	"""The one bit the Deal form script needs. The settings document itself holds the
	webhook secret and the API identity, so reps get this and nothing else."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return bool(frappe.db.get_single_value("CRM Acumatica Settings", "enabled"))
```

In `get_crm_form_script` replace the `frappe.client.get_single_value` call with `call("crm.integrations.acumatica.api.is_enabled").then((enabled) => { if (enabled) this.doc.trigger("setAcumaticaActions") }).catch(() => {})`. `webhook.py`:

```python
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	stored = settings.get_password("webhook_verify_token", raise_exception=False)
```

Patch:

```python
import frappe


def execute():
	# webhook_verify_token was a Data field readable by every Sales User through
	# frappe.client.get_single_value; it is a Password field now. A plaintext value
	# left in tabSingles would fail to decrypt, so move it into the encrypted store.
	value = frappe.db.get_single_value("CRM Acumatica Settings", "webhook_verify_token")
	if not value or value.startswith("*"):
		return
	settings = frappe.get_doc("CRM Acumatica Settings")
	settings.webhook_verify_token = value
	settings.flags.ignore_validate = True
	settings.save(ignore_permissions=True)
```

- [ ] **Step 4: Run the package; all green.** Reinstall `test_site` first if the migrate of the JSON change is needed: `bench --site test_site migrate`.

- [ ] **Step 5: Commit** — `fix: the Acumatica webhook secret and API identity are closed to reps`.

---

### Task 2: Webhook key in a header; branch sent; CustomerID length

**Files:**
- Modify: `crm/integrations/acumatica/webhook.py`, `crm/integrations/acumatica/client.py`, `crm/integrations/acumatica/outbound.py`
- Modify: `crm_acumatica_settings.json` (new field `customer_id_max_length`, Int, default `10`, description "Acumatica's CUSTOMER ID segment length; only used with From Organization Name", placed after `customer_numbering`)
- Tests: `test_webhook.py`, `test_client.py`, `test_outbound.py`

- [ ] **Step 1: Failing tests.**

`test_webhook.py`:
```python
	@patch("crm.integrations.acumatica.webhook.frappe.enqueue")
	def test_key_in_header_is_accepted(self, enqueue):
		_set_token("hdr-secret")
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		frappe.local.request = FakeRequest(args={}, headers={"X-Vectora-Key": "hdr-secret"})
		self.assertEqual(handle_notification(), {"ok": True})
		enqueue.assert_called_once()
```
(`FakeRequest` — extend whatever the file already fakes so it carries `.headers`; a `types.SimpleNamespace(args=..., headers=...)` is enough.)

`test_client.py`:
```python
	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_branch_is_sent_on_the_token_request_when_set(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "t", "expires_in": 3600})
		rget.return_value = _resp(200, [])
		s = _settings(branch="MAIN")   # follow the file's existing settings-stub helper
		AcumaticaClient(s).get_page("Customer")
		self.assertEqual(rpost.call_args.kwargs["data"]["branch"], "MAIN")
```
and a sibling asserting `"branch" not in data` when unset.

`test_outbound.py::TestCreateCustomer`:
```python
	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_customer_id_from_name_respects_the_segment_length(self, ClientCls):
		_enable(customer_numbering="From Organization Name", customer_id_max_length=10)
		org, deal = _make_deal(status="Won")   # ensure the org name is longer than 10 chars
		client = MagicMock(); ClientCls.return_value = client
		client.put.return_value = {"NoteID": {"value": "n"}, "CustomerID": {"value": "X"}}
		outbound.push_customer_for_deal(deal.name)   # Task 3 renames the worker; if Task 3 has not run yet call create_customer_in_acumatica(deal, "on_update")
		self.assertLessEqual(len(client.put.call_args.args[1]["CustomerID"]), 10)
```

- [ ] **Step 2: Run, expect failures.**

- [ ] **Step 3: Implement.**

`webhook.py`:
```python
	# The header is the primary channel: a query-string key lands in every access
	# log between Acumatica and this process. ?key= stays for destinations that
	# cannot set a header.
	key = None
	if frappe.request:
		key = frappe.request.headers.get("X-Vectora-Key") or frappe.request.args.get("key")
```
Update the module comment to document the header (`X-Vectora-Key: <token>`).

`client.py::_token`: build `data = {...}`; `if getattr(s, "branch", None): data["branch"] = s.branch`; post `data=data`.

`outbound.py`: `limit = int(settings.get("customer_id_max_length") or 10)`; `payload["CustomerID"] = re.sub(r"[^A-Z0-9]", "", org.organization_name.upper())[:limit]` (import `re`). Keep the comment: Acumatica's default CUSTOMER ID segment is 10; the setting exists for tenants that widened it.

- [ ] **Step 4: Run the package; green.**
- [ ] **Step 5: Commit** — `fix: the Acumatica webhook key travels in a header, branch is sent, CustomerID fits the segment`.

---

### Task 3: Customer push off the request thread

**Files:**
- Modify: `crm/integrations/acumatica/outbound.py`, `crm/hooks.py`
- Tests: `crm/integrations/acumatica/test_outbound.py` (`TestCreateCustomer` calls the worker; `TestHook` asserts the hook enqueues; `TestTransportFailures` calls the worker)

**Interfaces:**
- Produces: `outbound.queue_customer_push(doc, method)` — the `CRM Deal` `on_update` hook; cheap checks, then `frappe.enqueue("crm.integrations.acumatica.outbound.push_customer_for_deal", deal=doc.name, queue="short", job_id=f"acumatica_customer_{doc.organization}", deduplicate=True, enqueue_after_commit=True)`.
- Produces: `outbound.push_customer_for_deal(deal: str) -> None` — the worker; the old body of `create_customer_in_acumatica`, loading the deal by name and re-checking the conditions (the status may have moved on).
- `create_customer_in_acumatica(doc, method)` is kept as a thin alias of `queue_customer_push` for one release so a site with a stale hooks cache does not error; mark it deprecated in a comment.

- [ ] **Step 1: Failing tests.** Change every `outbound.create_customer_in_acumatica(deal, "on_update")` in `TestCreateCustomer`/`TestTransportFailures` to `outbound.push_customer_for_deal(deal.name)`. Add to `TestHook`:

```python
	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_the_deal_save_enqueues_the_push_instead_of_calling_the_erp(self, enqueue):
		_enable(create_customer_on_status_change=1, deal_status="Won")
		org, deal = _make_deal(status="Won")
		outbound.queue_customer_push(deal, "on_update")
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.args[0], "crm.integrations.acumatica.outbound.push_customer_for_deal")
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertEqual(enqueue.call_args.kwargs["job_id"], f"acumatica_customer_{org.name}")

	def test_handler_registered_on_deal_update(self):
		self.assertIn(
			"crm.integrations.acumatica.outbound.queue_customer_push",
			frappe.get_hooks("doc_events")["CRM Deal"]["on_update"],
		)
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement** as in Interfaces. The worker: `doc = frappe.get_doc("CRM Deal", deal)`, then the existing condition block and body unchanged. `hooks.py`: replace the `create_customer_in_acumatica` entry with `queue_customer_push`.
- [ ] **Step 4: Run the package; green.**
- [ ] **Step 5: Commit** — `fix: the Acumatica customer push runs in a background job, not inside the deal save`.

---

### Task 4: A sales quote refuses unlinked lines

**Files:** `crm/integrations/acumatica/outbound.py`, `crm/integrations/acumatica/test_outbound.py`

- [ ] **Step 1: Failing test** in `TestCreateSalesQuote`:

```python
	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_refuses_when_any_product_is_unlinked_and_names_it(self, ClientCls):
		_enable()
		org, deal = _mapped_deal()                     # one linked product
		unlinked = frappe.get_doc({"doctype": "CRM Product", "product_code": "NO-ACU-1", "product_name": "Unlinked"}).insert(ignore_permissions=True)
		deal.append("products", {"product_code": unlinked.name, "qty": 1, "rate": 5})
		deal.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError) as cm:
			outbound.create_sales_quote_from_deal(deal.name)
		self.assertIn("NO-ACU-1", str(cm.exception))
		ClientCls.return_value.put.assert_not_called()
```
(If `_mapped_deal` creates product codes differently, follow its idiom; the assertion is that the *name* of the unlinked product appears and nothing was sent.)

- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.** Replace the `continue` with collecting `unlinked.append(row.product_code)`; after the loop: `if unlinked: frappe.throw(_("These products are not linked to Acumatica inventory items: {0}. Run a backfill or link them, then try again.").format(", ".join(unlinked)))`. Drop the now-redundant `if products and not details` branch.
- [ ] **Step 4: Run; green.**
- [ ] **Step 5: Commit** — `fix: a sales quote is refused, not silently shortened, when a product is not linked`.

---

### Task 5: One sync at a time, and failures retried

**Files:**
- Modify: `crm/integrations/acumatica/importer.py`, `crm/integrations/acumatica/api.py`, `crm/integrations/acumatica/webhook.py`, `crm/hooks.py`
- Modify: `crm_acumatica_settings.json` — add `pending_retries` (JSON, hidden, read-only) and `last_sync_error` (Small Text, read-only) in the sync section; `crm_acumatica_settings.py` — helpers
- Tests: `test_importer.py`, `test_api.py` (`test_sweep_is_registered_daily_long` now expects `schedule_sweep`), `test_webhook.py` (job id)

**Interfaces:**
- `importer.SYNC_JOB_ID = "acumatica_sync"`; `importer.MAX_RETRY_ATTEMPTS = 5`
- `importer.schedule_sweep()` — scheduler entry: `frappe.enqueue("crm.integrations.acumatica.importer.nightly_sweep", queue="long", job_id=SYNC_JOB_ID, deduplicate=True, timeout=BACKFILL_TIMEOUT)` guarded by `enabled`. `api.start_backfill` and `webhook.handle_notification` use `SYNC_JOB_ID` too. (`BACKFILL_TIMEOUT` moves from `api.py` to `importer.py`; `api.py` imports it.)
- `run_backfill` body is wrapped in `with filelock("acumatica_sync", timeout=0):` (import from `frappe.utils.synchronization`); on `LockTimeoutError` return `{"skipped": "another sync is running"}` and write that to `last_sync_error`? No — a skip is not an error; log with `frappe.logger("acumatica").info(...)` and return.
- Retry queue: settings field `pending_retries` holds `{"Customer": {"<noteid>": attempts}, ...}`. In `run_backfill`: (a) before the entity loop, for each pending `(entity, noteid)`: fetch with `client.get_page(entity, top=1, filter=f"NoteID eq guid'{noteid}'")`; if a record comes back, upsert it inside the same savepoint/issue pattern; on success remove from pending; on failure `attempts += 1`, and at `MAX_RETRY_ATTEMPTS` remove and `record_sync_issue(entity, noteid, "Gave Up", last error)`; if nothing comes back (deleted in Acumatica) remove silently. (b) In the main loop's `except`, after `record_sync_issue`, add the record's NoteID to pending with `attempts = 1` (only when it has a NoteID). Persist with `frappe.db.set_single_value("CRM Acumatica Settings", "pending_retries", json.dumps(pending))` before the final commit.
- The outer body of `run_backfill` is wrapped in `try/except Exception as e:` that writes `str(e)[:500]` to `last_sync_error` (through `frappe.db.set_single_value` + commit) and re-raises; a successful run clears it.
- `record_sync_issue` gains a `kind` value `"Gave Up"`: add it to the `kind` Select options of `CRM Acumatica Sync Issue` (`crm/fcrm/doctype/crm_acumatica_sync_issue/crm_acumatica_sync_issue.json`).

- [ ] **Step 1: Failing tests** in `test_importer.py::TestBackfill` (mock `AcumaticaClient` as the file already does):

```python
	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_failed_record_is_retried_next_sweep_and_given_up_after_the_cap(self, ClientCls):
		client = MagicMock(); ClientCls.return_value = client
		bad = {"NoteID": {"value": "bad-1"}, "CustomerID": {"value": "C1"}, "CustomerName": {"value": ""}}  # no name -> upsert raises
		client.iter_all.side_effect = lambda entity, **kw: [bad] if entity == "Customer" else []
		client.get_page.return_value = [bad]
		_enable()
		run_backfill()
		pending = json.loads(frappe.db.get_single_value("CRM Acumatica Settings", "pending_retries") or "{}")
		self.assertEqual(pending["Customer"]["bad-1"], 1)
		client.iter_all.side_effect = lambda entity, **kw: []
		for _ in range(MAX_RETRY_ATTEMPTS - 1):
			run_backfill()
		pending = json.loads(frappe.db.get_single_value("CRM Acumatica Settings", "pending_retries") or "{}")
		self.assertNotIn("bad-1", pending.get("Customer", {}))
		kinds = [r.kind for r in frappe.get_doc("CRM Acumatica Settings").sync_issues]
		self.assertIn("Gave Up", kinds)

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_retried_record_that_now_succeeds_leaves_the_queue(self, ClientCls):
		# same setup; second run's get_page returns a record WITH a CustomerName; assert the org exists and pending is empty

	def test_two_syncs_do_not_run_at_once(self):
		from frappe.utils.synchronization import filelock
		with filelock("acumatica_sync", timeout=0):
			self.assertEqual(run_backfill(), {"skipped": "another sync is running"})

	def test_a_crashing_run_leaves_its_error_on_the_settings(self):
		with patch("crm.integrations.acumatica.importer.AcumaticaClient", side_effect=RuntimeError("boom")):
			_enable()
			with self.assertRaises(RuntimeError):
				run_backfill()
		self.assertIn("boom", frappe.db.get_single_value("CRM Acumatica Settings", "last_sync_error"))
```

`test_api.py`: `test_sweep_is_registered_daily_long` asserts `"crm.integrations.acumatica.importer.schedule_sweep" in frappe.get_hooks("scheduler_events")["daily_long"]`; `test_start_backfill_enqueues_on_long_queue` asserts `job_id == "acumatica_sync"`. `test_webhook.py::test_valid_key_enqueues_sweep` asserts the same job id.

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement** as in Interfaces. Note on `filelock`: it needs a writable site directory (`sites/<site>/acumatica_sync.lock`); tests run on `test_site`, which is writable.
- [ ] **Step 4: Run the package; green.**
- [ ] **Step 5: Commit** — `fix: one Acumatica sync at a time, and a record that fails is retried before it is given up on`.

---

### Task 6: Connection test and a status the panel can show

**Files:**
- Modify: `crm/integrations/acumatica/client.py` (`ping()`), `crm/integrations/acumatica/api.py` (`test_connection`, `get_sync_status`)
- Tests: `test_client.py`, `test_api.py`

**Interfaces:**
- `AcumaticaClient.ping() -> dict` — `get_page("Customer", top=1, select="CustomerID")`, returns `{"ok": True, "sample": <CustomerID or None>}`; errors propagate as `AcumaticaError`/`requests.RequestException`.
- `api.test_connection() -> dict` — `frappe.only_for(["System Manager", "Sales Manager"], True)`; uses the *saved* settings (`frappe.get_doc`, not cached — the operator just saved); requires `instance_url`; forces a fresh token (`frappe.cache().delete_value(client._cache_key())` first); returns `{"ok": True, "sample": ...}` or `{"ok": False, "error": "<status and first 300 chars of body, or the exception text>"}` — never throws for a transport failure, so the panel can print it.
- `api.get_sync_status()` returns `{"last_synced_at", "open_issues", "running": is_job_enqueued(SYNC_JOB_ID), "last_sync_error", "pending_retries": <count>}`.

- [ ] **Step 1: Failing tests.** `test_client.py`: `test_ping_fetches_one_customer` (mock post/get; assert params `$top == 1`). `test_api.py::TestConnection`: with `AcumaticaClient` patched to raise `AcumaticaError("x", status_code=401, body="bad creds")` → `test_connection()["ok"] is False` and `"401" in error`; with `ping` returning a sample → ok; `test_connection` rejects non-managers; `get_sync_status` carries the new keys.
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run; green.**
- [ ] **Step 5: Commit** — `feat: an Acumatica connection test, and a sync status that says what is running and what last broke`.

---

### Task 7: The settings panel — errors shown, token generated, issues listed, connection tested

**Files:** `frontend/src/components/Settings/AcumaticaSettings.vue`

No component tests exist; verify by `cd frontend && yarn test:run` (unchanged) and by reading the rendered panel on the dev site if a browser is available (not required to pass the task).

- [ ] **Step 1: Save errors.** Replace `settings.save.submit()` with `settings.save.submit(null, { onSuccess: () => toast.success(__('Settings saved')), onError: (e) => toast.error(e.messages?.[0] || __('Could not save the settings')) })`.

- [ ] **Step 2: Token.** The field is a Password now, so the saved value never comes back. Render `<FormControl type="password" v-model="settings.doc.webhook_verify_token" :label="__('Webhook Verify Token')" :description="tokenHint" />` beside a `Button` labelled `__('Generate')` that sets `settings.doc.webhook_verify_token` to 32 URL-safe random chars from `crypto.getRandomValues` and shows it once in a `toast.success(__('Token generated — copy it into Acumatica before you save: {0}', [token]))`; `tokenHint` reads: "Paste into Acumatica's push notification as header X-Vectora-Key. Stored encrypted; generate a new one if lost."

- [ ] **Step 3: Test connection.** A `Button` `__('Test connection')`, disabled while `testing`, that first saves (`await settings.save.submit()`), then `call('crm.integrations.acumatica.api.test_connection')` and toasts `ok ? __('Connected — first customer: {0}', [sample || '—']) : error`.

- [ ] **Step 4: Status + issues.** `loadStatus` also fetches `crm.integrations.acumatica.api.get_open_sync_issues` into `issues`. Below the status line render: `{{ __('Sync') }}: {{ status.running ? __('running') : __('idle') }}`, `status.last_sync_error` in `text-ink-red-9` when set, `status.pending_retries` when > 0, then a list of issues (`entity · remote_id · kind · detail · detected_on`) each with a ghost `Button` `__('Dismiss')` calling `dismiss_sync_issue({ issue_name })` and reloading. Empty state: `__('No open sync issues')`.

- [ ] **Step 5: Backfill.** `Run backfill` is disabled when `status?.running`; after queueing, poll `loadStatus` every 5 s while `running` (clear the interval on unmount).

- [ ] **Step 6: `yarn test:run` green; commit** — `feat: the Acumatica panel shows save errors, generates the webhook token, tests the connection and lists sync issues`.

---

### Task 8: A bulk import that does not notify

**Files:**
- Modify: `crm/fcrm/doctype/crm_deal/crm_deal.py` (`assign_agent`), `crm/integrations/acumatica/spreadsheet.py`
- Tests: `crm/fcrm/doctype/crm_deal/test_crm_deal.py` (new test), `crm/integrations/acumatica/test_spreadsheet.py` (new test)

**Interfaces:**
- `frappe.flags.bulk_assign_quietly` — when truthy, `CRMDeal.assign_agent` writes the ToDo directly (no Notification Log, no email, no share msgprint) and shares the document only if the agent cannot read it:

```python
		if frappe.flags.bulk_assign_quietly:
			# A file import assigns thousands of deals in one run. assign_to._add
			# notifies on every one -- a Notification Log row, an email and an RQ job
			# each -- which on the first production import tripped max_queued_jobs and
			# left 4,000 muted mails to purge. The ToDo is the assignment; the rest is
			# noise for a rep who was not at their desk when the data arrived.
			frappe.get_doc(
				{
					"doctype": "ToDo",
					"allocated_to": agent,
					"reference_type": "CRM Deal",
					"reference_name": self.name,
					"assigned_by": frappe.session.user,
					"status": "Open",
					"description": self.get_title() if hasattr(self, "get_title") else self.name,
				}
			).insert(ignore_permissions=True)
			if not frappe.has_permission("CRM Deal", "read", self, user=agent):
				frappe.share.add("CRM Deal", self.name, agent, notify=0)
			return
```
- `spreadsheet.import_workbooks` sets `frappe.flags.bulk_assign_quietly = True` for its duration (reset in `finally`, next to the dry-run flag).
- `spreadsheet.upsert_deal`: wrap `doc.save(...)` in a retry for `frappe.QueueOverloaded` — up to 3 attempts with `time.sleep(2)` between; re-raise on the last. (Belt and braces: with notifications off there should be no jobs, but a site automation may still enqueue.)

- [ ] **Step 1: Failing tests.** `test_crm_deal.py`:

```python
	def test_a_quiet_bulk_assignment_writes_the_todo_and_nothing_else(self):
		before = frappe.db.count("Notification Log")
		frappe.flags.bulk_assign_quietly = True
		try:
			deal = create_test_deal(...)   # follow the file's factory; set deal_owner to a Sales User
		finally:
			frappe.flags.bulk_assign_quietly = False
		self.assertTrue(frappe.db.exists("ToDo", {"reference_type": "CRM Deal", "reference_name": deal.name, "status": "Open"}))
		self.assertEqual(frappe.db.count("Notification Log"), before)
```
`test_spreadsheet.py`: a test that runs `import_workbooks(...)` on the fixture workbooks the file already uses and asserts `Notification Log` count did not grow and every created deal has an Open ToDo.

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `crm.fcrm.doctype.crm_deal.test_crm_deal` and the package; green.**
- [ ] **Step 5: Commit** — `fix: the spreadsheet import assigns deals without a notification storm`.

---

### Task 9: Documentation

**Files:** `.pi/feats/acumatica/README.md`

- [ ] **Step 1:** Document: the webhook header (`X-Vectora-Key`) and the Acumatica push-notification setup (SM302000: URL `https://<site>/api/method/crm.integrations.acumatica.webhook.handle_notification`, header name/value); the connection test; the retry queue and "Gave Up" issues; `last_sync_error`; `customer_id_max_length`; that the customer push is a background job; that the sales-quote action refuses unlinked products; the import's quiet assignment (and remove the now-unneeded `max_queued_jobs` and purge-before-unmute steps from the runbook, keeping `mute_emails 1` as belt-and-braces); and the known gaps (deletions/inactive not mirrored, no 429 backoff beyond `request_pause`, contacts unlinked on `BusinessAccount` change are not re-linked).
- [ ] **Step 2: Commit** — `docs: the Acumatica README covers the hardened integration`.

---

## Self-review

- Spec coverage: findings 1 (T1), 2 (T3), 3 (T5), 4 (T4), 5 (T5), 6 (T2), 7 (T2), 8 (T6+T7), 9 (T7), 10 (T2), 11 (T8), 12 (T9). ✓
- Type consistency: `SYNC_JOB_ID`, `MAX_RETRY_ATTEMPTS`, `BACKFILL_TIMEOUT` live in `importer.py` from Task 5 on; `api.py` and `webhook.py` import them. `push_customer_for_deal(deal: str)` (Task 3) is what Task 2's outbound test calls — Task 2 runs before Task 3, so its test calls `create_customer_in_acumatica(deal, "on_update")` and Task 3 renames the call.
- Placeholders: Task 5's second test and Task 8's tests name the factory to follow rather than inventing one; the implementer reads the file's existing helpers (`_enable`, `_make_deal`, `create_test_deal`) and uses them verbatim.
