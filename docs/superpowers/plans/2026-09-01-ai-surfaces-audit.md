# Audit record — 2026-09-01 (pre-MBP demo)

Four read-only sweeps of the whole app plus a security review of the
`feat/ai-surfaces` diff, run after the Mentor, Assistant and Analyst landed.
Every finding below was read in the source by a second pass before it was
accepted; the sweeps' own coverage lists are in the session transcript. The
branch-diff security review reported **no findings** at or above its
confidence bar (it checked the knowledge endpoints' gates and mass
assignment, `ask_analyst`'s System Manager gate, the ERP OData filter inputs,
secret handling in the ERP adapters, the two new `v-html` sinks and every
model-output render).

Status: **fixed** = in this branch; **deferred** = recorded here with the
reason; **by design** = reviewed and kept.

## Permissions (whitelisted endpoints)

| # | Where | Finding | Status |
|---|---|---|---|
| P1 | `crm/fcrm/doctype/crm_deal/crm_deal.py` `create_deal` | No permission check, then `insert(ignore_permissions=True)`: any authenticated account could create deals, contacts and organizations. | fixed |
| P2 | `crm/api/quota.py` `get_quota_grid` | Managers read every rep's target through `_sales_users()`, escaping the hierarchy scoping their lists have. | fixed — `visible_reps()` |
| P3 | `crm/api/quota.py` `set_quota`, `copy_quota_forward` | Any Sales Manager could write another team's targets (`ignore_permissions=True`). | fixed — subtree check |
| P4 | `crm/api/contact.py` `get_linked_deals` | Deal values, owners and contact details returned without a deal read check (Sales User has read on all Contacts). | fixed — `get_list` |
| P5 | `erpnext_crm_settings.py` `check_customer_for_quotation` | Creates an ERP Customer for a deal the caller may not write. | fixed |
| P6 | `crm/api/suggestions.py` `get_dismissal_stats` | Any manager could read any rep's dismissal reasons. | fixed — `visible_users()` |
| P7 | `crm_view_settings.py` `create` and kanban column sync | Enumerated any Link target of any doctype (e.g. Email Account names) without a read check. | fixed |
| P8 | `crm/domain_enrichment/evals/runner.py` `run_and_print` | A `bench execute` helper was whitelisted: any user could run the model eval suite. | fixed — decorator removed |
| P9 | Metadata endpoints in `crm/api/doc.py`, `crm_fields_layout.py`, `crm/api/__init__.py` | Schema of any doctype readable via `get_meta(doctype)`. Low. | fixed — read gate |
| P10 | `crm_view_settings.py` `public` | A Sales Manager could publish or reassign another user's private view. | fixed |

Not a finding, worth knowing: `convert_to_deal` honours `doc.flags.ignore_permissions` on a caller-supplied doc, but frappe's type validation rejects a dict for a `Document` parameter, so it is unreachable from the wire. Every dashboard aggregate goes through `scope_deals`/`scope_leads`/`visible_reps`; no interpolated SQL anywhere in `crm/`.

## Outbound calls, limits, jobs

| # | Where | Finding | Status |
|---|---|---|---|
| O1 | `crm/integrations/api.py` `get_recording_url` | Provider API key and secret sent as Basic auth to whatever host a user-editable `recording_url` names. | fixed — credentials only to the provider's host; rate-limited |
| O2 | `crm/domain_enrichment/model_fallback.py` | Model output written to a record with no human action (auto-enrich and scheduled re-enrichment). | **deferred** — the fallback is an opt-in admin setting (off by default) and changing it alters an existing feature's behaviour the day before a demo. Follow-up: apply model-sourced values only on a manual trigger, and surface them as a proposal otherwise. |
| O3 | `model_fallback.py` | Model calls bypassed the daily budget and inflight slot. | fixed |
| O4 | `crm/domain_enrichment/api.py` | `enrich`, `retry`, `enrich_preview` were IP-limited only (comment claimed per-user). | fixed |
| O5 | `crm/api/exchange_rate.py` | Same. | fixed |
| O6 | `erpnext_crm_settings.py` `get_erpnext_site_client` | `FrappeClient` had no timeout; reachable from three endpoints and every deal save at the trigger status. | fixed — `(5, 30)` |
| O7 | `lead_sync_source/facebook.py` | `make_get_request` has no timeout. | fixed |
| O8 | `exotel/handler.py` `make_a_call` | Billable call, no rate limit. | fixed |
| O9 | `acumatica/importer.py` `run_backfill` | A failing record was caught but not rolled back, so a partial upsert could be committed with the next batch. | fixed — savepoint per record |
| O10 | `lead_syncing/background_sync.py` | Per-source except without rollback. | fixed |
| O11 | `crm_invitation.py` `expire_invitations` | One bad row aborted the day's expiries. | fixed |
| O12 | `CRM Exotel Settings.webhook_verify_token` is a Data field readable by Sales Manager; Sales User has read on the integration Singles. | Sole guard on the guest webhook is readable in-app. | **deferred** — turning it into a Password field and dropping the read grants touches settings pages that Sales Managers use; do it with the settings UI change, after the demo. |

Fine as found: the agent tier (limits, budgets, slot, timeouts, `allow_redirects=False`, no write path for model output), the enrichment SSRF guard, every scheduled job's isolation except O9–O11.

## Query hot spots and bundle

| # | Where | Finding | Status |
|---|---|---|---|
| Q1 | `crm/api/doc.py` `delete_bulk_docs` | Synchronous unlink loop, uncapped items, load+save per linked row. | fixed — capped, unlink moved into the job |
| Q2 | `crm/api/doc.py` `get_linked_docs_of_document` | `get_doc` per linked record for one title field. | fixed — one `get_list` per doctype |
| Q3 | `crm/api/activities.py` | `get_attachments` per comment and per communication (comments are unlimited). | fixed — one File query per doctype |
| Q4 | `crm/api/activities.py` | `get_linked_calls` called three times per request. | fixed |
| Q5 | `crm/api/contact.py` `update_deals_email_mobile_no` | Two queries per deal on every Contact save. | fixed |
| Q6 | `crm/api/doc.py` `get_data` | `page_length` unbounded from the client. | fixed — capped |
| Q7 | `crm/api/rep_plan.py` `_set_suggestion_status` | Two round-trips per item, up to 400 per save. | fixed |
| Q8 | `crm/api/dashboard.py` `get_base_currency_symbol` | Uncached Currency read on ~10 charts per dashboard view. | fixed — cached value |
| Q9 | `rep_planning.py` `_match_plan`, `_close_stranded_items`; `take_forecast_snapshot`; `get_deal_health` full-doc load; `convert_to_deal` per-assignee assign | Daily/weekly job and per-page constant overheads. | **deferred** — measurable but not user-facing latency; batch as a follow-up. |
| B1 | Entry bundle | The full Lucide sprite (1,777 symbols, ~488 KB) is inlined because 64 `lucide-*` names are still rendered by name in ~154 files. | **deferred** — a migration to Phosphor components, not a patch. |
| B2 | Critical path | The tiptap/prosemirror editor stack (941 KB raw) is statically imported from the entry via `TextEditorControl`. | **deferred** — `defineAsyncComponent` is a small change but needs a QA pass on every form with a Text Editor field. |
| B3 | Post-login | Twilio voice SDK (~300 KB) loads for every user via `CallUI`. | **deferred** — same reason. |
| B4 | PWA | The service worker precaches the entire build (195 entries, 7.3 MB) on first visit. | **deferred** — restrict `globPatterns` to entry + preloads. |
| B5 | `ViewControls.vue` | Whole-lodash import for one `isEqual`. | fixed |
| B6 | `utils/index.js` `isEmoji` | Rebuilt a 1,800-entry array on every call. | fixed — module-level Set |

Build numbers at the time of the sweep: 165 JS chunks, 6.7 MB raw / ~2.0 MB gzip; initial critical path 2.8 MB raw / 779 KB gzip JS plus 708 KB / 70 KB gzip CSS.

## Frontend HTML sinks

| # | Where | Finding | Status |
|---|---|---|---|
| H1 | `Controls/AttachControl.vue` | `:href` bound to a raw Attach value; a `javascript:` value set through `set_value` runs on click. | fixed — scheme allowlist |
| H2 | `utils/dialogs.jsx` | `$dialog({ html })` rendered unsanitised (reachable from Form Scripts). | fixed |
| H3 | `utils/index.js` `sanitizeHTML` | DOMPurify defaults keep `<style>`, `<form>` and `target=_blank` without `rel`. | fixed — forbid list, `rel` hook |
| H4 | `stores/suggestions.js` | Reply draft inserted into the editor unsanitised (safe today only because of tiptap's schema). | fixed — belt and braces |
| H5 | `Settings/CalendarSettings.vue` | Translated strings via `v-html` unsanitised (admin trust boundary). | fixed |
| H6 | `AttachmentArea.vue`, `WhatsAppArea.vue` | `window.open` without `noopener`. | fixed |
| H7 | frappe-ui `paste-html-utils.ts` | Clipboard HTML parsed on a live element (needs the victim to paste attacker HTML). | **deferred** — third-party; report upstream. `htmlToText` in `utils/index.js` moved to `DOMParser` so it cannot become the same sink. |

Verified text-only: every render of Mentor, Assistant and Analyst output, thread summaries and reply drafts; every `v-html` in the app goes through `sanitizeHTML` at the binding (list in the sweep).
