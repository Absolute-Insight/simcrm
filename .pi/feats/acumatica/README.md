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
`true`/`false`/`null`:

```
bench --site <site> execute crm.integrations.acumatica.spreadsheet.import_workbooks --kwargs '{
  "customers": "sites/<site>/private/files/mbp/Customers 20260902.xlsx",
  "sales_orders": "sites/<site>/private/files/mbp/Sales Orders 20260902.xlsx",
  "invoices": "sites/<site>/private/files/mbp/Invoices 20260902.xlsx",
  "owners": "sites/<site>/private/files/mbp/owners.json",
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

Reps will see one in-app assignment notification per imported deal on
first login even with emails muted.

Preconditions, in order: custom fields exist; the owner users exist;
`FCRM Settings.currency` is ZAR; no enabled CRM Automation Rule on
CRM Deal / Created, or you have decided to let each fire ~4,000 times;
`mute_emails` is `1` in site config; a manual `bench backup --with-files`;
`clear_demo_data()` has run. After the run: check `Email Queue` and
`Notification Log` counts, drain or purge the default RQ queue, then
`set-config mute_emails 0`.
