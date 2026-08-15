# Phase 8 — Proactive Agent Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The system watches structured CRM data, detects deals/leads that need attention, and proposes concrete next actions as `CRM Suggestion` records — deterministic first, model-free, fully testable. This slice ships the backend spine (doctype, signal engine, scheduler, API); the inbox UI and the model-assisted tiers build on it.

**Architecture:** Signals are pure detection functions over rows (unit-testable without a site) with a thin `frappe` query layer feeding them. A runner dedupes against open/recently-dismissed suggestions, inserts new ones, and expires stale ones, on the hourly scheduler. Everything works with the agent tier disabled — the model, when it arrives, ranks and enriches; it never gates.

**Tech stack:** Frappe doctype JSON + Python, bench run-tests against `dev.localhost`.

**Spec:** `.pi/PLAN.md` § Phase 8 (components 1–3 of 5 in this slice).

## Decisions taken (PLAN.md "decisions needed", resolved with its recommendations)

1. **First signal set**: `idle_deal`, `no_next_step`, `lead_sla` — none need historical data.
2. **Inbox placement**: shell panel + per-record section (UI slice, next).
3. **Dismiss/snooze semantics**: a dismissed (signal, reference) pair is a 14-day cooldown —
   the runner will not re-emit it until the cooldown lapses; accepting behaves the same
   (the action was taken; if the state recurs later, the signal may fire again). Open
   suggestions never duplicate. Suggestions expire after 14 days open.

## Signal definitions (v1 thresholds are module constants)

| Signal | Fires when | Proposed action |
|---|---|---|
| `idle_deal` | Deal whose status type is Open/Ongoing with no activity (Communication, CRM Task update, CRM Call Log, Comment) in 7 days | `create_task` — "Re-engage {org}" |
| `no_next_step` | Same deal population with no open CRM Task and empty `next_step` | `create_task` — "Set the next step" |
| `lead_sla` | Lead with an SLA where `first_response_time` is unset and `response_by < now` (or `sla_status = 'Failed'`) | `create_task` — "Respond now" (due immediately) |

Suggestion is targeted at `deal_owner` / `lead_owner` (falls back to unset → visible to managers).

---

### Task 1: `CRM Suggestion` doctype

**Files:**
- Create: `crm/fcrm/doctype/crm_suggestion/crm_suggestion.json` (+ `.py`, `__init__.py`)

Model on `crm_task` (autoincrement naming; System Manager / Sales Manager / Sales User perms).
Fields: `signal` (Data, reqd), `reference_doctype` (Link DocType, reqd), `reference_docname`
(Dynamic Link, reqd), `suggested_action` (Select: create_task/schedule_call/send_reply/update_field),
`action_payload` (JSON), `rationale` (Small Text), `factors` (JSON), `score` (Float),
`user` (Link User), `status` (Select: Open/Accepted/Dismissed/Expired, default Open),
`dismiss_reason` (Small Text), `expires_on` (Datetime).

- [ ] Doctype JSON + controller (no behavior yet)
- [ ] `bench --site dev.localhost migrate` creates the table
- [ ] Commit

### Task 2: Signal engine (`crm/agent/signals.py`) — TDD

Pure detection functions take plain rows + `now` and return suggestion dicts; a thin
query layer feeds them; `run_signals()` dedupes, inserts, expires. Update
`crm/agent/tests/test_layering.py`'s map: `signals` may import `frappe` and `config`-tier
modules only (never `client` — signals are model-free by constraint 3 of PLAN.md).

- [ ] `crm/agent/tests/test_signals.py` — pure-function tests first: idle boundary (6.9 vs 7.1 days), no-next-step (open task suppresses; filled `next_step` suppresses), lead SLA (responded suppresses; no SLA suppresses), dedupe (open blocks, dismissed-in-cooldown blocks, dismissed-past-cooldown allows), expiry marking
- [ ] Implement pure functions: `find_idle_deals(rows, activity, now)`, `find_missing_next_step(rows, open_tasks)`, `find_sla_breached_leads(rows, now)`, `dedupe(candidates, existing, now)`
- [ ] Implement query layer + `run_signals()` (aggregate queries, no N+1) + `expire_stale()`
- [ ] Integration test: seed a stale deal on the test site, `run_signals()`, assert one `CRM Suggestion`; run twice, assert still one
- [ ] All tests green via `PYTHONPATH=/workspace bench --site dev.localhost run-tests --app crm --module crm.agent.tests.test_signals`
- [ ] Commit

### Task 3: Scheduler + API

**Files:** `crm/hooks.py` (hourly entry), Create: `crm/api/suggestions.py`

- [ ] `hooks.py` hourly: `crm.agent.signals.run_signals`
- [ ] `crm/api/suggestions.py` whitelisted: `get_suggestions()` (open, for session user or all for managers, permission-checked reads), `dismiss(name, reason)`, `accept(name)` — accept/dismiss only flip status + audit; record creation happens client-side through the normal create flow behind `formDialog()` (write-gate constraint)
- [ ] Endpoint tests (`test_suggestions_api.py`): non-owner cannot dismiss another user's suggestion unless Sales Manager
- [ ] Commit

### Task 4: Deal health score (`crm/agent/predict.py`) — TDD

Explainable heuristic on structured features only: days since activity, days in current
stage (from `status_change_log`), close-date proximity/overrun, open-task presence,
inbound/outbound balance. Returns `{score: 0..100, factors: [{key, label, weight}]}` —
factors always shipped, never a bare number.

- [ ] `test_predict.py` first: monotonicity (more idle days → lower score), factor attribution sums, boundary cases
- [ ] Pure `score_deal(features)` + thin `get_deal_health(name)` wrapper
- [ ] Commit

### Task 5 (next slice): Inbox UI + accept flow

Shell panel + per-record section; accept opens pre-filled `formDialog()`; realtime badge
via `$socket`. Uses `dataviz`/design tokens from Phase 7. Not in this slice.

## Verification

- `PYTHONPATH=/workspace bench --site dev.localhost run-tests --app crm` (server suite)
- `cd frontend && yarn test:run` (unchanged, must stay green)
- Manual: `bench execute crm.agent.signals.run_signals` on the seeded dev site, then
  `frappe.get_all("CRM Suggestion")` shows expected rows; re-run is idempotent.
