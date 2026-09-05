# Acumatica integration

Two-way sync with a client's Acumatica ERP. One ERP per deployment: enabling
either integration requires the other to be disabled. The rule is enforced on
both saves — `CRM Acumatica Settings.validate` refuses while SIMERP (ERPNext) is
on, and `install.block_dual_erp`, wired to ERPNext CRM Settings' `validate`
through this app's `doc_events`, refuses the other direction.

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
  When no `NoteID` matches, an import *adopts* a CRM record with the same
  natural key (organization name, product code, contact name or primary email)
  rather than creating a rival — a record already linked to a different NoteID
  is left alone and reported as a sync issue.
- `outbound.py` — customer-on-deal-status (mirrors the ERPNext trigger shape)
  and `create_sales_quote_from_deal`.
- `webhook.py` — receiver for Acumatica Push Notifications (SM302000). The
  webhook only *triggers* a pull; the payload is ignored. **The nightly sweep is
  the correctness mechanism** — Acumatica retains failed notifications for only
  2 days, so webhooks must never be the only sync path.

Only one sync runs at a time. The manual **Run backfill** button, every webhook
notification and the nightly sweep all enqueue under the same job id
(`SYNC_JOB_ID = "acumatica_sync"`, in `importer.py`), so the queue's
`deduplicate` collapses a burst of them — and `run_backfill` also takes a site
filelock of the same name, because queue dedup is best effort (a `bench execute`
call reaches it with no queue at all) and the lock is what actually keeps two
importers off the same pages. The scheduler (`daily_long` → `schedule_sweep`)
only enqueues `nightly_sweep`; it does not run the sweep inline, since a first
sync can take hours and would otherwise hold a scheduler worker. A sync that
finds another one already running (lock or queue) skips quietly rather than
erroring — that's the ordinary case, not a fault.

A record an entity's upsert can't handle (a name collision, a bad value) is
logged as an "Import Failed" sync issue and queued in the settings' hidden
`pending_retries` JSON field, keyed by NoteID per entity. Because nothing about
a mishandled record changes in Acumatica, the `LastModifiedDateTime` filter
would never offer it again — so every sweep re-fetches whatever is queued, by
NoteID, before it does its normal filtered pass. After `MAX_RETRY_ATTEMPTS` (5)
failures the record is dropped from the queue and gets a "Gave Up" sync issue
instead of retrying forever. A run that dies outside any single record's
try/except (expired credentials, a dropped connection) writes its message to
`last_sync_error` and re-raises, so an admin sees more than a high-water mark
that quietly stopped moving; the next clean run clears it.

## Customer push (outbound)

`outbound.queue_customer_push` is the CRM Deal `on_update` hook — cheap checks
only (enabled, status match, organization present), then it enqueues
`push_customer_for_deal` on the `short` queue, deduplicated per organization
(`job_id=f"acumatica_customer_{organization}"`) and only `enqueue_after_commit`,
so a slow or unreachable Acumatica never blocks the rep's save. The worker
reloads the deal, re-checks the same conditions (time has passed since the hook
fired), and does the HTTP PUT; a transport or API failure lands as a "Push
Failed" sync issue rather than dying silently in the worker log.
`create_customer_in_acumatica` still exists as a thin deprecated alias, kept
for one release so a site with a stale hooks cache pointing at the old name
does not error.

`CustomerID` derived from the organization name (`customer_numbering` =
*From Organization Name*) strips non-alphanumerics and truncates to
`customer_id_max_length` (Int, default `10` — Acumatica's stock CUSTOMER ID
segment); widen the setting if the tenant's segment was widened. The token
request also sends `branch` in the body whenever the setting is non-empty —
some tenants reject a login that doesn't name one.

**Create Sales Quote** (`create_sales_quote_from_deal`) refuses the whole quote
if any product on the deal is not linked to an Acumatica inventory item
(`CRM Product.acumatica_id` unset) — the failure names the unlinked product
codes so they can be fixed and retried. It used to skip an unlinked row and
still save a shortened quote with a success toast, which gave the rep no signal
that a line was silently dropped.

## Webhook setup (Acumatica side)

In Acumatica, under **Push Notifications** (screen SM302000), point the
destination at:

```
https://<site>/api/method/crm.integrations.acumatica.webhook.handle_notification
```

Method: **POST** only — the endpoint is `@frappe.whitelist(methods=["POST"])`,
a GET is refused. Set header `X-Vectora-Key` to the value of **Webhook Verify
Token** from the settings panel (its own **Generate** button fills this with a
random 32-byte token, shown once in a toast so it can be pasted across before
saving). The header is the primary channel — a query-string key would land in
every access log between Acumatica and this process — but `?key=<token>` on the
URL still works as a fallback for a destination that cannot set a header.

The token itself is stored as a `Password` field (`webhook_verify_token`),
decrypted only through `get_password()`; it is never exposed to reps. Reps
don't get read access to the settings document at all — the Deal form script
that decides whether to show the Acumatica actions calls the whitelisted
`crm.integrations.acumatica.api.is_enabled()`, which returns only the one bit
(`enabled`) it needs, rather than reading the singleton (which also holds the
webhook secret and the API identity) through `frappe.client.get_single_value`.

## Diagnostics: connection test and sync status

The settings panel's **Test connection** button saves the form first, then
calls `api.test_connection()`. It forces a fresh OAuth token (the operator may
have just changed credentials, and a cached token from the old ones would test
those instead) and never raises — a transport failure, a 401, a missing
Instance URL are all returned as `{"ok": False, "error": ...}` for the button to
show, since a stack trace is not what "test connection" is for. On success it
returns a sample `CustomerID` from one cheap read-only page
(`AcumaticaClient.ping()`).

`api.get_sync_status()` (System Manager / Sales Manager only) reports:
`last_synced_at`, `open_issues` (undismissed sync issues), `running` (whether
`SYNC_JOB_ID` is currently enqueued or executing, via `is_job_enqueued`),
`last_sync_error`, and `pending_retries` (a count across all entities, not the
queue itself — the panel shows a number, not a list to walk).

The panel also lists open sync issues with a **Dismiss** button per row
(`get_open_sync_issues` / `dismiss_sync_issue`), and shows the backfill state:
**Run backfill** disables itself while a sync is `running`, and polls
`get_sync_status` every 5s after queuing until it stops.

## Operational notes

- Acumatica licences cap API request rates; `request_pause` throttles paging.
  Check the client's licence tier before promising a backfill timeline.
- `endpoint_version` differs per instance (default `24.200.001`); a 404 on the
  entity URL usually means the version, not the entity, is wrong.
- Historical quotations are NOT imported as deals — fabricated deal history
  would poison forecasting, health scoring, and quota analytics.

## Known limitations

- A contact's primary email is only ever appended to, never replaced: if the
  address changes in Acumatica, the old one stays primary in the CRM and the new
  one lands beside it. Fix the primary flag by hand until the importer learns to
  re-point it.
- A contact whose `BusinessAccount` changes in Acumatica (moved to a different
  customer) is not re-linked in the CRM — `upsert_contact` only sets
  `company_name` when it resolves a `BusinessAccount`, it never clears or
  re-points an existing link on update.
- Deletions and inactive customers in Acumatica are not mirrored — the importer
  only ever upserts what the API still returns; a customer deactivated or
  deleted on the Acumatica side stays as-is in the CRM.
- No backoff beyond `request_pause` for HTTP 429 (rate limiting) — a burst that
  trips the tenant's rate limit surfaces as an ordinary transport failure (a
  sync issue, or a `test_connection` error), not a retry-with-backoff.

## Spreadsheet import (one-way, integration off)

`crm/integrations/acumatica/spreadsheet.py` loads Acumatica's Excel exports
without enabling the integration. Design and every mapping decision:
`docs/superpowers/specs/2026-09-03-mbp-acumatica-import-design.md`.

The identity custom fields (`acumatica_noteid`, `acumatica_id`, the two Deal
fields) are schema, not a feature: `after_install` and `after_migrate` create
them on every site, so a site on a build that includes #166 has them without
the integration ever being enabled. **Do not enable CRM Acumatica Settings to
get them** on an older build — enabling arms the ERP write paths (see the
spec's Prerequisite 1). Repair or pre-#166 sites:

```
bench --site <site> execute crm.integrations.acumatica.install.ensure_custom_fields
```

Put the workbooks and an `owners.json` (`{"018": "rep@example.com", ...}`)
under the site's private files, then dry-run. `--kwargs` is evaluated as a
Python literal, not parsed as JSON — write `True`/`False`/`None`, not
`true`/`false`/`null`. Paths are absolute: `bench execute` runs with the
`sites/` directory as its working directory, so `sites/<site>/...` does not
resolve (it failed that way on the first production run):

```
P=/home/frappe/frappe-bench/sites/<site>/private/files/mbp
bench --site <site> execute crm.integrations.acumatica.spreadsheet.import_workbooks --kwargs '{
  "customers": "'$P'/Customers 20260902.xlsx",
  "sales_orders": "'$P'/Sales Orders 20260902.xlsx",
  "invoices": "'$P'/Invoices 20260902.xlsx",
  "owners": "'$P'/owners.json",
  "rates": {"USD": 18.2},
  "window_days": 90,
  "quote_validity_days": 30,
  "dry_run": True
}'
```

Read the reject rows in the output. When they are all expected, run again
with `"dry_run": False`. Re-running is safe: organizations key on
`acumatica_id`, deals on `acumatica_sales_quote`, and `import-manifest.json`
next to the Sales Orders file stops a re-run resurrecting a deal a rep
deleted; a deal a rep has since edited is left alone rather than
overwritten. Purchase Orders are not imported (no customer link). A dry run
never commits — the importer suppresses its periodic commits for the
duration and rolls everything back at the end. A real run that raises
part-way keeps the batches already committed (every 50 rows) and rolls back
the current one; because every importer is idempotent, the fix is to
re-run, not to restore.

The reader aborts the whole file on a ragged row (a row with more or fewer
cells than the header); the dry run reads all three workbooks before
writing anything, so this surfaces first. Confirm no blank or duplicated
header cell in any `Data` sheet — a duplicated header silently drops a
column.

Under `frappe.flags.bulk_assign_quietly` (set for the whole run by
`import_workbooks`), `CRMDeal.assign_agent` writes the assignment `ToDo`
directly instead of going through `assign_to._add` — and shares the deal with
the agent only if they cannot already read it. `assign_to._add` is what wrote a
`Notification Log` row, queued an email and enqueued an RQ job for *every*
assignment; on the first production run that was 4,052 of each, which tripped
`max_queued_jobs` and left thousands of muted emails to purge afterward. With
the quiet path there is no `Notification Log` row and no email queued at
all — only the `ToDo` (and, where needed, the share). `upsert_deal`'s
`doc.save()` also retries up to 3 times, 2s apart, on `frappe.QueueOverloaded`,
in case some other site automation still enqueues mid-run.

Reps will see no in-app or email assignment notification from the import —
their deals simply appear assigned (an open `ToDo`) next time they look.

Preconditions, in order: custom fields exist (installed by migrate since
#166); the owner users exist — every salesperson code on an in-window quote
must be in `owners.json` or its quotes are rejected, so map the codes you
cannot resolve (Acumatica's `017` "Admin", the `999` catch-all) to
`Administrator` rather than leaving them out; `FCRM Settings.currency` is
ZAR; no enabled CRM Automation Rule on CRM Deal / Created, or you have
decided to let each fire ~4,000 times; `mute_emails` is `1` in site config as
belt-and-braces — the quiet assignment path queues no email regardless, but
mute is free insurance against anything else a deal save triggers; a manual
`bench backup --with-files`; `clear_demo_data()` has run.

After the run: wait for the RQ queues to drain (`bench doctor`, or `llen` on
`rq:queue:*`), then `set-config mute_emails 0`. The old
`max_queued_jobs`/purge-before-unmute steps are gone from this runbook — the
quiet assignment path is what removed the need for them, not a workaround
that still has to be undone by hand.
