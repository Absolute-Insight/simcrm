# Mentor, Assistant and Analyst — design

**Date:** 2026-09-01
**Status:** approved in session; drives `docs/superpowers/plans/2026-09-01-ai-surfaces.md`
**Deadline context:** demo to MBP Engineers (valves, actuators, flow meters,
steel fabrication; Boksburg / Rustenburg / KZN) at lunch on 2026-09-02, from the
production stack at vectora.absolute-insight.ai.

## Goal

Three model-backed conversational surfaces, each with its own knowledge source
and permission tier, built on the existing agent tier's contract (guided
decoding, degrade-never-raise, per-user rate limit, daily budget, no
model-written SQL, model output is untrusted text):

| Surface | Where | Who | Knows | Endpoint |
|---|---|---|---|---|
| **Mentor** | Help center, above the search field | every CRM user | the shipped help articles | `crm.agent.api.ask_mentor` |
| **Assistant** | Sidebar slide-out panel (existing) | every sales user | the admin-curated knowledge base, optionally the product catalogue | `crm.agent.api.ask_assistant` |
| **Analyst** | New page `/analyst`, sidebar entry for admins | System Manager, and only after an explicit grant | CRM figures from the metrics layer; ERP invoice and payment figures when an ERP integration is enabled | `crm.agent.api.ask_analyst` |

Then: the help center gains an "AI & automation" category that explains every
automatic and model-backed capability for non-technical readers; the app is
audited and patched; the suites and a browser QA pass run; a release is cut and
production upgraded and verified; a report is published.

## Non-goals

- No model-generated SQL, ever. The analyst picks from a catalogue; code runs
  the query.
- No new write capability for any model tier.
- No equipment predictive-maintenance model: the CRM holds no installed-base
  or service history. "Maintenance" in the analyst means accounts and deals
  predicted to go quiet, from the existing deterministic signals. Equipment
  maintenance is a follow-up that depends on ERP installed-base data.
- No chat persistence. Transcripts stay in memory per session, as today.

## 1. Shared chat component and store factory

`frontend/src/components/AgentChat.vue` — the transcript, the pending
indicator, the `disabled` / `unavailable` states, the example-question
buttons and the input. Extracted from `Assistant.vue` without behaviour
change. Props: `messages`, `asking`, `failure`, `examples`, `intro`,
`placeholder`, `compact`; slots `message-extra` (per assistant message: chips,
tables) and `disabled-actions`; emits `send`, `retry`, `clear`. Answers render
with `{{ }}` only.

`frontend/src/stores/agentChat.js` — `createChatStore({ method, mapResult })`
returns `{ visible, messages, asking, failure, ask, retry, clear, toggle }`.
The existing `stores/assistant.js` becomes one instance (method
`ask_assistant`); `stores/mentor.js` and `stores/analyst.js` are two more.
History handling (last 8 turns, sent separately from the question) is shared.

## 2. Mentor

Help center layout: a Mentor block sits above the search field in the left
column — a one-line input with the sparkle icon and the placeholder "Ask the
mentor how Vectora works". Sending a question switches the right pane from the
article to the Mentor transcript (an `AgentChat` in the pane, full height);
clicking an article in the tree or a citation chip switches back to the
article and keeps the transcript. A "Back to conversation" chip appears in the
pane header while a transcript exists. Chips deep-link as they do today.

Backend: `ask_mentor` is the current `ask_assistant` body, unchanged in
behaviour: help-article grounding through `knowledge.select_articles`, the
existing `SYSTEM_PROMPT` (renamed `MENTOR_SYSTEM_PROMPT`), citation filter
against the real article names, `AssistantAnswer` schema.

## 3. Assistant over the knowledge base

### Doctype `CRM Knowledge Article` (`crm/fcrm/doctype/crm_knowledge_article/`)

| Field | Type | Notes |
|---|---|---|
| `title` | Data, required | |
| `category` | Data | free text; grouped in the settings page |
| `body` | Markdown Editor, required | what the assistant quotes |
| `available_to_assistant` | Check, default 1 | off = kept but never quoted |
| `product` | Link → CRM Product | optional; lets a product's article surface when the product is named |
| `tags` | Data | comma-separated; counted like title words when scoring |

Naming `format:KB-{#####}`. Permissions: System Manager create/read/write/
delete; Sales Manager and Sales User read. Content is admin-authored, so it is
trusted the way help articles are; it is still rendered as text, never HTML,
in any model answer.

### Settings

`CRM Agent Settings` gains `assistant_reads_products` (Check, default 0):
when on, enabled `CRM Product` rows are turned into article dicts
(`title = product_name`, content = code, description as plain text, standard
rate with the base currency) and scored alongside the knowledge articles.
Reads are permission-checked `frappe.get_list` under the asking user.

New Settings page **Knowledge** (System Manager only): list grouped by
category with search, an editor dialog (title, category, tags, product,
available-to-assistant, markdown body with a live preview), delete with
confirm, and **Import sample knowledge**, which loads
`crm/knowledge/samples/*.md` (same frontmatter contract as help articles
plus optional `tags` and `product`), skipping any title that already exists.
The sample pack is a valve knowledge base: ball, butterfly, gate, globe,
check, knife-gate, control, relief and safety valves, actuators (electric,
pneumatic, hydraulic), flow meters (magnetic, ultrasonic), materials and
trims, pressure classes and end connections, standards and certifications
(ISO, API, ANSI, BS, SABS; ISO 9001/45001/14001), and a selection guide by
industry (mining and minerals, water and wastewater, petrochemical, power,
pulp and paper, food and beverage). Each sample says at the top that it is
sample content to replace with the company's own.

### Backend

`crm/api/knowledge.py`: `list_articles` (read permission), `save_article`,
`delete_article`, `import_samples` (System Manager, rate-limited 6/min).
`crm/knowledge/__init__.py`: the sample loader, frappe-free, reusing
`crm.help.parse_article`.

`crm/agent/knowledge.py` gains `ASSISTANT_SYSTEM_PROMPT` ("You answer a sales
rep's questions about the company's products, offering and industries, from
the knowledge base below only...") and `build_assistant_messages` takes the
prompt as a parameter so both surfaces share the selection and documentation
block. Scoring already accepts any dict with `name`, `title`, `content`; tags
are appended to the title for scoring.

`ask_assistant` (rewritten): sales-user gate, rate limit and budget as today;
loads articles with `available_to_assistant = 1` (get_list, fields name,
title, category, body, tags, product) plus products when the toggle is on;
selects; completes into `AssistantAnswer`; returns
`{"status": "ok", "answer", "sources": [{"name", "title"}]}` filtered against
what was loaded. When there are no articles at all the endpoint returns
`{"status": "empty"}` and the panel explains that an administrator has not
added knowledge yet (admins get a button to Settings → Knowledge).

Panel copy: intro "Ask about our products, models, materials, standards and
which industries use what. Answers come only from the knowledge base your
administrator maintains." Example questions come from the sample pack.

## 4. Analyst

### Gate

`CRM Agent Settings.analyst_enabled` (Check, default 0, label "Allow the
analyst to read CRM and ERP data"). `ask_analyst`:

1. `frappe.only_for("System Manager")`.
2. `cfg.enabled` off → `{"status": "disabled"}`; `analyst_enabled` off →
   `{"status": "disabled", "reason": "analyst_off"}`.
3. Rate limit and budget as the other tiers (one budget unit per question,
   though the question costs two model calls — documented).

The sidebar entry and the route are admin-only in the frontend as well; the
page shows the grant state with a link to Settings → Assistant.

### Catalogue (`crm/agent/analyst.py`, pure)

A dict of metric descriptors: `key`, `title`, `description` (what the model
reads to choose), `source` (`crm` or `erp`), `columns`. Model-facing names:

CRM: `won_revenue_by_month`, `forecast_by_month`, `pipeline_by_stage`,
`funnel_conversion`, `quota_attainment_by_rep`, `deals_at_risk`,
`sales_trend`, `growth_rates`, `leads_by_source`, `deals_by_industry`,
`deals_by_territory`, `deals_by_salesperson`, `plan_adherence_by_rep`,
`average_deal_value`, `time_to_close`, `revenue_projection`,
`accounts_going_quiet`.

ERP (listed only when an ERP integration is enabled): `erp_invoices_by_month`
(invoiced amount and count), `erp_payments_by_month` (cash received),
`erp_receivables` (open invoices and overdue), `erp_cashflow_by_month`
(payments in against invoices out, net).

Pure functions in the same module: `plan_from_model(raw, available_keys,
today)` normalises an `AnalystPlan` (drops unknown metrics, caps at four,
defaults the period to the last twelve months, orders dates);
`fallback_plan(question, available_keys)` picks by keyword when the model
returns nothing usable; `project_revenue(months, horizon=3)` (least-squares
line over the monthly series, clamped at zero, returns points and the slope
per month); `build_plan_messages` and `build_answer_messages` (system prompt
states that every number in the answer must come from the figures block, that
the figures are the only truth, and that a question the figures cannot answer
gets "the data does not cover that").

### Data (`crm/agent/analyst_data.py`)

`run_plan(plan) -> list[table]` calls the metrics layer in
`crm.api.dashboard` for CRM metrics under the caller's own session (its
scoping already applies), and the ERP adapters for ERP metrics:

- Acumatica: `SalesInvoice` (`Date`, `Amount`, `Balance`, `Status`, `Type`)
  and `Payment` (`ApplicationDate`, `PaymentAmount`, `Type`) through
  `AcumaticaClient.iter_all` with a date filter, capped at 5,000 rows.
- ERPNext: `Sales Invoice` (`posting_date`, `grand_total`,
  `outstanding_amount`, `due_date`, `status`) and `Payment Entry`
  (`posting_date`, `paid_amount`, `payment_type`) through its REST API with
  the stored key and secret.

An adapter failure yields a table with `error: "unreachable"` and the answer
prompt is told that source was unavailable; the CRM tables still run. Every
table: `{key, title, source, columns, rows, period, note}`; monetary values
are in the base currency, and ERP values are labelled with the ERP name.

`accounts_going_quiet` reuses `crm.agent.signals` activity features and
`predict.score_deal`: open deals whose cadence ratio exceeds the cooling
threshold or that carry slip risk, grouped by organization, with the days
since last contact and the health score.

### Schemas

`AnalystPlan { metrics: list[str] (max 4), from_date: str, to_date: str,
reasoning: str (max 300) }` and `AnalystAnswer { answer: str (max 4000),
highlights: list[str] (max 5), caveats: list[str] (max 3) }`, both
`extra="forbid"`.

### Response and page

`{"status": "ok", "answer", "highlights", "caveats", "tables", "period",
"sources": ["CRM", "Acumatica"]}`. `pages/Analyst.vue` renders the
transcript with the narrative, highlight bullets, caveats, and each table as a
sortable list (frappe-ui `ListView` shape used by Reports) with a CSV export
button reusing `utils/reportExport.js`. The figures on screen are the
computed tables, never numbers parsed out of the narrative. Example prompts:
"How did revenue grow over the last six months?", "Which reps are behind
quota this quarter?", "Which deals and accounts are likely to go quiet?",
"Project revenue for the next quarter", and, when an ERP is connected, "What
came in as cash last month against what we invoiced?".

## 5. Help center: AI & automation

`CATEGORY_ORDER` becomes: Getting started, Working with records, Proactive
selling, Analytics & reporting, **AI & automation**, Customisation. Existing
"Assistant & customisation" articles move to one of the two new categories.

New articles, written for a non-technical reader with the same three
headings each — *What it does for you*, *When it runs*, *What it never does*:

- `ai-and-automation.md` — the map: a table of every capability, whether it
  is deterministic (signals, deal health, planner proposals, forecasts and
  snapshots, digests, automation rules, ERP sync, website enrichment, SLA)
  or model-backed (Mentor, Assistant, Analyst, thread summaries, reply
  drafts), and the one sentence that matters for each.
- `mentor.md`, `assistant.md` (rewritten), `analyst.md`, `knowledge-base.md`
  (for admins: curating what the assistant may say).
- `automation-rules.md`, `suggestions.md`, `deal-health.md`, `digests.md`
  gain the three headings where missing; `welcome.md` links the map.

## 6. Audit, fixes, QA

After the features: `/security-review` on the branch plus a parallel sweep of
the whole app by four read-only agents — permission gates on every
`@frappe.whitelist` (including guest-allowed ones), every `v-html` and
`innerHTML` path, rate limits and budgets on outbound calls, and query hot
spots and bundle size. Findings are verified before they are fixed; each fix
is its own commit with a test where the finding is testable. Then `/test`
(vitest, `bench run-tests --app crm` on `test_site`, Playwright), then a
Playwright browser pass on the dev site in both themes covering the three
surfaces, Settings → Knowledge, the help center, and the existing smoke paths.

## 7. Release and production

PR from `feat/ai-surfaces` to `develop`, merged on green. `/release` promotes
to `main`, semantic-release tags v3.7.0, `builds.yml` is dispatched on the tag
and the manifest is verified in ghcr. Then the documented upgrade on the
`deploy/` stack: backup with files, maintenance mode on, edit the override and
`.env` tags, pull, up, migrate, maintenance mode off, `bench doctor`. Then a
Playwright pass on https://vectora.absolute-insight.ai against the live model,
including importing the sample knowledge and enabling the analyst as
Administrator so the demo is ready. The prod upgrade waits for the user's
confirmation.

## 8. Report

An HTML artifact: what shipped and where to find it, the audit findings and
fixes, test evidence with counts, prod verification, the deliberate
exclusions (equipment maintenance, chat persistence, model-written SQL) and
what to say in the demo about each surface.

## Testing

- Python: `test_knowledge_api.py` (permissions, sample import idempotence,
  availability filter), `test_analyst.py` (pure: plan normalisation,
  fallback, projection maths, prompt contents), `test_analyst_api.py` (gate
  order, degrade paths, budget, ERP adapter stubs and the unreachable
  table), `test_mentor_api.py` (the moved assistant tests), layering map
  additions for `analyst` (pure) and `analyst_data`.
- Frontend: unit tests for the chat store factory and the analyst table
  formatting; e2e smoke for the help center Mentor block and the Assistant
  empty state.
- Live: the eval runner's injection table does not apply to Mentor and
  Assistant (no untrusted content in the prompt); the analyst carries only
  computed numbers and the question, so it does not join it either.
