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
