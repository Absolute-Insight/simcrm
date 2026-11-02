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
| Sales quotes | Acumatica | created from a deal via the **Create Sales Quote** action; their outcome flows back (`outcomes.py`) |

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
finds another one already running (lock or queue) does not error — that's the
ordinary case, not a fault — but it is not silent either: `filelock` writes an
Error Log row ("Filelock: Failed to aquire …") before raising `LockTimeoutError`,
which `run_backfill` catches and logs at info level rather than treating as a
failure. So a skipped sync leaves an Error Log row behind, even though nothing
about it needs attention.

A record an entity's upsert can't handle (a name collision, a bad value) is
logged as an "Import Failed" sync issue and queued in the settings' hidden
`pending_retries` JSON field, keyed by NoteID per entity. Because nothing about
a mishandled record changes in Acumatica, the `LastModifiedDateTime` filter
would never offer it again — so every sweep re-fetches whatever is queued, by
NoteID (`client.get_by_id`, i.e. `GET …/<Entity>/<id>` — a record's `id` is its
NoteID; a 404 means it was deleted and the entry is dropped), before it does its
normal filtered pass. After `MAX_RETRY_ATTEMPTS` (5)
failures the record is dropped from the queue and gets a "Gave Up" sync issue
instead of retrying forever. A run that dies outside any single record's
try/except (expired credentials, a dropped connection) writes its message to
`last_sync_error` and re-raises, so an admin sees more than a high-water mark
that quietly stopped moving; the next clean run clears it.

## Quote outcomes and expiry (`outcomes.py`)

Every sweep, after the entity passes, reads the quotes (`SalesOrder`, the
configured `quote_order_type`) changed since the high-water mark — the field is
`LastModified`, not `LastModifiedDateTime` — and closes the deals that carry
their number in `acumatica_sales_quote`: **Completed** (the quote was copied
into a sales order) → Won, dated by the quote's last change; **Canceled** /
**Rejected** → Lost with the reason named. A deal a rep already closed is left
alone. A full backfill (`start_backfill`) reads every quote, which is how the
outcomes decided between the spreadsheet export and the first live sync were
caught up.

Acumatica never expires a quote, so the validity rule lives here: an open deal
whose `expected_closure_date` (the validity date, set by the import) is more
than `quote_expiry_grace_days` (default 30, 0 = off) in the past is marked
**Expired** — unless a rep edited it in the last 14 days, in which case it is
theirs to decide. Expired (`crm_deal_status.EXPIRED`, type On Hold, created by
`ensure_expired_status`) is not a close: it drops out of the weighted open
pipeline but the deal can still be won or lost, by a rep or by the quote's
outcome above. Lost only ever comes from Acumatica (Canceled/Rejected) or a
person. Before Expired existed the sweep closed these as Lost, reason "Quote expired";
patch `add_expired_deal_status` reopened those as Expired. Health scoring does not bump `modified`, so that guard
measures people, not jobs.

## Customer push (outbound)

Off by default (`create_customer_on_status_change`). `outbound.queue_customer_push`
is the CRM Deal `on_update` hook — cheap checks only (enabled, status match,
organization present), then it enqueues `push_customer_for_deal` on the `short`
queue, deduplicated per organization (`job_id=f"acumatica_customer_{organization}"`)
and only `enqueue_after_commit`, so a slow or unreachable Acumatica never blocks
the rep's save. The worker reloads the deal and re-checks the same conditions
(time has passed since the hook fired). A transport or API failure lands as a
"Push Failed" sync issue rather than dying silently in the worker log.
`create_customer_in_acumatica` still exists as a thin deprecated alias, kept for
one release so a site with a stale hooks cache pointing at the old name does not
error.

The worker, in order:

1. **Already linked** (`acumatica_id` or `acumatica_noteid`) — copy the code onto
   the deal and stop. This is every organization the sync or the spreadsheet
   import brought in.
2. **Completeness gate**, local reads only, before any request: organization
   name; an `address` (Address doc) with line 1, city and a country; a primary
   contact on the deal (`contacts` row with `is_primary`, or the only row) with a
   first name and an email or phone; `new_customer_class` set. Anything missing →
   no request at all, a **"Push Blocked"** sync issue naming what is missing, and
   one in-app note (CRM Notification, via `notify_user`) to the deal owner saying
   what to fill in.
3. **Unanswered earlier push** (in-flight marker). The marker holds the send time,
   the `CustomerName` and `CustomerID` *as sent* (recovery looks for those, not the
   organization's current name — it may have been renamed since; the CRM
   Organization `after_rename` hook moves the marker to the new docname), and the
   CustomerIDs Acumatica already had *by that name* before the PUT. Under
   AutoNumber the recovery reads by name, drops those and any code an organization
   here holds: exactly one left is adopted, none means the PUT made nothing (send
   again), more than one is a "Push Failed" for a manager to link by hand. Under
   From Organization Name the id was checked free before sending, so finding it is
   finding ours. A marker from before this change (a bare timestamp) adopts nothing.
4. **The confirmation**: `acumatica_confirmed_for` holds JSON `{hash, past}` —
   `confirmation_hash` (normalised name, VAT digits, primary-contact email) of what
   the manager confirmed, and the candidate codes they confirmed it is *not*. While
   the hash still matches, candidates in `past` are ignored; any other candidate
   still blocks, and a rename (hash mismatch) puts everything back in play.
5. **Local duplicates** (candidates in `past` excepted) — one read of every linked
   organization (~1,100 rows): same VAT number (digits only); the same name or a
   similar one (`matching.normalise_name`: casefold, `&`→and, punctuation and
   legal-form tokens — pty, ltd, cc, holdings… — and a trailing "COD" dropped; then
   equal, token-sorted `SequenceMatcher` ≥ 0.9, or all of one name's words (two or
   more) inside the other's, so "Bearing Man Group - Mozambique" is flagged against
   "Bearing Man Group (Pty) Ltd"); or the primary contact's email on a contact of a
   linked organization.
6. **Derived-id collision** (From Organization Name only), as before.
7. **Remote duplicates**: `CustomerName eq`, and `TaxRegistrationID eq` both as
   typed and as digits — separate reads. The name read always runs (it is what fills
   the marker's list). A read that fails is a "Push Failed", not a go-ahead.
8. Steps 4–7 run **without a lock** — they wait on Acumatica, and a row lock held
   across them stalled reps' saves of the organization and managers' actions. Only
   then is the organization re-read `for_update`: already linked → stop; the
   confirmation changed since step 4 → stop (the job `confirm_new_customer` queued
   decides on it); an in-flight marker this run did not start with → stop (another
   job sent a PUT that got no answer; the next push recovers what it made). Then
   PUT, link, **commit** — so no later failure in the job can
   roll the link back.

Any duplicate hit → no PUT; a **"Possible Duplicate"** sync issue whose detail names
the candidates and whose hidden `candidates` column (JSON: `customer_id`,
`organization`, `organization_name`, `reasons`) drives the settings panel, plus a
note to the deal owner that a manager is reviewing it — without the candidates,
which may be another rep's customers.

Sync-issue rows are written one row at a time (`record_sync_issue` inserts the
child row; `upsert_sync_issue` and `dismiss_sync_issues` update rows), never by
saving the Single: concurrent jobs saving it collided on the timestamp check, and a
save from a stale copy wrote it back. `CRMAcumaticaSettings.validate` reloads the
table from the database, so a stale form save keeps the log as it is. The push
keeps **one open row per organization and kind** — a repeat updates it in place
and does not notify again; moving from Push Blocked to Possible Duplicate (or back)
dismisses the other, the deal leaving the trigger status dismisses both, and a
successful push dismisses Blocked, Duplicate and Push Failed. A deal leaving the
status dismisses the organization's waiting rows only when none of its deals is
still in the status.

A settings save never touches the log: `validate` drops the rows from the document
and the controller's `update_child_table` skips the table (a test that means to
rewrite it sets `flags.write_sync_issues`), so neither a stale form copy nor the
document `frappe.client.save`/`set_value` hands back carries rows. Who may read
the log: the `sync_issues` table is permlevel 1 (System Manager only), which keeps
it out of `frappe.client.get` — but frappe lists a Single's child rows to anyone who
can read the Single (`get_list(child, parent_doctype=…)` checks the parent only), so
the settings' `has_permission` hook refuses the whole document to a manager whose
customers are scoped. Their panel shows "Connection settings are managed by a System
Manager" in place of the settings, and below it the status and their own issue
list with its actions. The log reaches them only through `get_open_sync_issues`
(and `get_sync_status` counts the same rows and withholds the last sync error's
text), which **fails closed** for them: a row is shown only
if its organization resolves (Customer / Customer Salesperson: `remote_id`; Contact:
its `company_name`; Deal: its organization; anything else hidden) and is
`customer_visible`, candidates that are someone else's organization are dropped, and
the detail is kept only for Push Blocked (it names fields), rebuilt from the visible
candidates for Possible Duplicate, and replaced for every other kind. Their
`dismiss_sync_issue` accepts only a row that list would show them, and
`confirm_new_customer` refuses an organization whose duplicate row has a candidate
they cannot see — a manager who sees every customer must review that one.

Resolution, in the settings panel's sync-issue list (`api.py`, POST only, System
Manager / Sales Manager, plus write permission on the organization):

- **Link to C-…** (`link_existing_customer`) — only offered for a candidate no
  organization here holds yet (a remote hit). Verifies the code exists in
  Acumatica, sets the organization's `acumatica_id`/`acumatica_noteid`, puts the
  code on its unlinked deals. A code another organization already holds is
  refused: two organizations on one customer is the split the sync cannot undo,
  so the fix is to move the deal to the organization that has it (the refusal
  names that organization only to a manager whose customers are not scoped).
- **Create as new** (`confirm_new_customer`) — for any candidate, a same-VAT match
  included (MBP holds several accounts for one taxpayer — branches; the dialog
  says so when the VAT matched). Needs a deal in the trigger status that passes the
  gate; stores `confirmation_hash` of it in `acumatica_confirmed_for` (a second
  confirm with no open row keeps the codes already confirmed past) and enqueues
  the push under its own job id (`acumatica_customer_<org>_confirm`), because a push
  already running under the ordinary id would swallow a deduplicated enqueue.

The panel reloads the settings document after every action, and shows issue times
as date and HH:mm.

`link_existing_customer` refuses a code another organization holds by
`acumatica_id`, or — once Acumatica answered — holds the customer's NoteID; it
writes the code onto every deal of the organization that has no quote number,
replacing a stale one.

The identity fields on CRM Organization (`acumatica_id`, `acumatica_noteid`,
`acumatica_confirmed_for`) and on CRM Deal (`acumatica_customer` — Create Sales
Quote prefers it — and `acumatica_sales_quote`, the quote's idempotency key) are
**permlevel 1**: a Sales User reads them, only a manager writes them. CRM Deal's
level-1 rows are in its JSON; patch `grant_acumatica_identity_permlevel` adds them
as Custom DocPerm only where a site customised the doctype's permissions. Contact
is frappe's doctype, whose standard permissions grant every role and which would
need Custom DocPerm (freezing it) for a level-1 row, so its `acumatica_id` /
`acumatica_noteid` are guarded by a validate hook (`install.guard_contact_identity`)
that restores them for anyone but a manager or an `ignore_permissions` save. `read_only`/`hidden` are the form's alone, so before this a
rep could `set_value` their organization onto another customer's code, or confirm
it themselves. The sync and the push write past it with `ignore_permissions` /
`db.set_value`. (`tax_registration_id` stays permlevel 0 — reps fill it in.)

What is sent (`_customer_payload`): `CustomerName`, `CustomerClass`
(`new_customer_class`, default COD — the class supplies terms, credit limit and
statement cycle, which are never sent, nor `Status`), `CurrencyID` (organization's,
else the base currency), `TaxZone` (`tax_zone_home` when the address country is
`home_country`, else `tax_zone_abroad`; blank → not sent), `TaxRegistrationID`,
`MainContact` {`Email`, `Phone1`, `WebSite`, `Address` {`AddressLine1`,
`AddressLine2`, `City`, `State`, `PostalCode`, `Country` (ISO-2 from the Country
doc)}}. `State`: a South African province in any spelling ("GP - Gauteng",
"KwaZulu-Natal") becomes MBP's code (GP NW MP LP KZN WC FS EC NC,
`matching.state_code`); elsewhere only a value that already looks like a code (≤3
alphanumerics) is sent. Nested entities are wrapped here — `client.wrap` passes a
dict through as already wrapped.

After the customer is linked and committed, two follow-ups, each of which only ever
records a sync issue:

- **Salesperson** — a separate PUT {`CustomerID`, `Salespersons: [{SalespersonID,
  Default: true}]`} when exactly one `salesperson_owners` code maps to the deal
  owner. Separate because a brand-new customer has no MAIN location yet, and a
  Salespersons row without a `LocationID` can be refused — which in the create PUT
  would refuse the customer. A failure is a "Push Failed" on entity "Customer
  Salesperson"; it is not retried.
- **Primary contact** — GET Contact under the new `BusinessAccount` by email (else
  first/last name), adopting what an earlier attempt made, or PUT one (`FirstName`,
  `LastName`, `Email`, `Phone1`, `JobTitle`, `BusinessAccount`); link the CRM
  Contact's `acumatica_id`/`acumatica_noteid`; then PUT Customer {`CustomerID`,
  `PrimaryContactID`}. A failure is a "Push Failed" on the Contact; a redis marker
  (`acumatica_inflight::CustomerContact::<org>`) remembers the follow-up is owed and
  the next deal save finishes it — only for a customer this push created, never an
  imported one. A contact already linked to Acumatica is left alone.

Retry for a blocked or failed push: (a) every deal save while it stays in the
status; (b) `queue_customer_push_for_organization` on CRM Organization
`on_update` — only for an unlinked organization with an **open Push Blocked or
Possible Duplicate row** and a deal in the status, so editing an organization with
a years-old won deal never creates it; (c) the sync (`_import_all`, after the
entities) calls `queue_pending_customer_pushes`: **at most once per 20 hours**
(cache timestamp — every Acumatica push notification runs the sync), unlinked
organizations (one row each) with a deal in the status modified in the last 30
days, at most 100 queued a run, resuming after the last organization the previous
run reached (cache cursor, wrapping at the end). An organization with an open
Blocked/Duplicate row is passed over unless it, its address, the deal or the
deal's primary contact was modified after the row was written. An Address or
Contact edited on its own saves neither deal nor organization; (c) is what
catches those.

Settings defaults on existing sites: frappe applies a Single's defaults only while
nothing is stored for it, so `install.ensure_customer_push_defaults`
(after_migrate) writes `new_customer_class` = COD and `home_country` = South
Africa where no row exists — never over a value an admin cleared.

The organization's **VAT Number** (`tax_registration_id`, custom field) is filled by
the sync from the Customer's `TaxRegistrationID` (top-level, so no `$select`
change) and never blanked by it. It is on the organization side panel: on enabling
(`ensure_layout_fields`), and on sites whose panel already shows the customer code
by patch `add_vat_number_to_organization_side_panel`, which places it right after
`acumatica_id` (it calls `ensure_custom_fields` first — patches run before the
after_migrate hook that creates the field).

`CustomerID` derived from the organization name (`customer_numbering` =
*From Organization Name*) strips non-alphanumerics and truncates to
`customer_id_max_length` (Int, default `10` — Acumatica's stock CUSTOMER ID
segment); widen the setting if the tenant's segment was widened. When `branch`
is set, every API request carries it as the `PX-CbApiBranch` header: under OAuth
there is no session to hold a branch, so Acumatica reads it per call, and without
the header a quote lands in the API user's default branch. (The token request
still names it in the body too; the identity server ignores what it does not
know.)

**Create Sales Quote** (`create_sales_quote_from_deal`) refuses the whole quote
if any product on the deal is not linked to an Acumatica inventory item
(`CRM Product.acumatica_id` unset) — the failure names the unlinked product
codes so they can be fixed and retried. It used to skip an unlinked row and
still save a shortened quote with a success toast, which gave the rep no signal
that a line was silently dropped.

A PUT Acumatica refuses is reported with Acumatica's own reason.
`AcumaticaError.detail()` walks the response JSON for it, because a rejected PUT
echoes the entity back with the `error` nested inside whichever field failed —
truncating the raw body usually cut the reason off. Writes get `WRITE_TIMEOUT`
(120s) against a read's 30s, and a quote that still times out tells the rep the
order may exist and to check before retrying: there is no idempotency key on a
SalesOrder PUT, so a blind retry is a duplicate order.

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

## API sessions and the concurrent-login limit

Every OAuth token holds one of the API user's **concurrent API logins** (Users,
SM201010) until it expires an hour later. The client therefore logs out
(`AcumaticaClient.logout()`, best effort, never raises) after every Test
connection click and at the end of every sync, whether it finished or died.
Deal-time calls (a quote, a customer push) keep the cached token — they are short
and share one session. Ask the tenant to set the API user's limit to **3**: a
sync, a rep's quote and an admin's Test connection can legitimately overlap. On
MBP's sandbox (2026-09-18) the default limit was reached on the first day of
testing, and every later call answered with the login page as HTML — which the
error parser now reports as such rather than as a stack of markup.

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

## Unproven until a real tenant answers

Written against documentation; none of this has met a live instance yet.

- ~~`$orderby=NoteID` on paged reads~~ — **confirmed accepted** on MBP's sandbox
  (Acumatica 25.201, endpoint Default/25.200.001) on 2026-09-18, as were the
  `datetimeoffset` filter, retrieve-by-id and the QT SalesOrder PUT (new quotes
  land On Hold; tax is applied from the customer).
- The full customer PUT (class, tax zone, nested `MainContact.Address`,
  `Salespersons`), the Contact PUT under a new `BusinessAccount` and the
  `PrimaryContactID` update are written against the 25.200.001 swagger and MBP's
  export, not yet exercised on the tenant.
- The quote PUT sends no `Branch`/`LocationID`/`CurrencyID`/`ManualPrice`, and
  the deal's currency is never compared with the customer's.

## Shapes the first live pull taught us (MBP, 2026-09-18)

- Several Acumatica customers share one name (three "Sibanye Rustenburg Platinum
  Mines (Pty) Ltd"). The second and later are created as `Name (CustomerID)`, never
  merged into the first; a re-sync keeps that name.
- A second contact with the same name at the same customer is a second contact
  (Contact's autoname suffixes it), not a refusal — Acumatica had "Portia Portia"
  twice at one account.
- `Phone1` sometimes holds a street address. An unusable phone is dropped and the
  contact still lands; Contact's own validation used to fail the whole person.
- Stock item descriptions run past `product_name`'s 140 characters: the name is
  cut with an ellipsis and the full text kept in `description`.

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
`bench backup --with-files`; `clear_demo_data()` has run; and, before a first
production run, `bench --site <site> set-config max_queued_jobs 50000` — one
more line of insurance. The quiet assignment path should make it unnecessary
(no `assign_to._add` job per assignment any more), but the run is not
otherwise instrumented for enqueue counts, so there's no cheap way to confirm
that from the run itself.

After the run: wait for the RQ queues to drain (`bench doctor`, or `llen` on
`rq:queue:*`), then `set-config mute_emails 0` and
`bench --site <site> set-config max_queued_jobs 500` to put the ceiling back.
The old purge-before-unmute step is gone from this runbook — the quiet
assignment path is what removed the need for it, not a workaround that still
has to be undone by hand. The `max_queued_jobs` bump stays, as insurance that
costs one line to set and one to undo.
