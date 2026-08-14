# Phase 9 — Rep Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reps plan their week as concrete activity items; the agent can propose a week from the suggestion queue (rep confirms — Phase 8 write gate); a daily matcher links plan items to the actual activity that fulfilled them, so plan-vs-actual is computed, never self-reported.

**Architecture:** Two doctypes (`CRM Rep Plan` parent, `CRM Rep Plan Item` child). Fulfilment matching is a pure function (rows in, assignments out) fed by batched queries — the same testability pattern as the Phase 8 signals. APIs are thin and ownership-checked.

**Spec:** `.pi/PLAN.md` § Phase 9.

## Decisions (resolving the plan's open questions)

1. **Week only** (plan's recommendation). `week_start` is always a Monday, validated.
2. **Managers view any plan, edit only their own** — least-surprise default; revisit if
   the team wants manager-authored plans (recorded as an open decision in PLAN.md).
3. **Matching window**: an actual fulfils an item when kinds match, references match
   (when the item names one), and the actual falls inside the item's plan week.
   One actual fulfils at most one item (greedy by date proximity).

## Activity kinds → actual sources

| Item `activity_type` | Fulfilled by | User linkage | Timestamp |
|---|---|---|---|
| Call | CRM Call Log | `owner` | `creation` |
| Task | CRM Task with status Done | `assigned_to` | `modified` |
| Email | Communication (Sent) | `owner` | `creation` |
| Meeting | Event | `owner` | `starts_on` |

### Task 1: Doctypes

- `CRM Rep Plan`: `user` (Link, reqd), `week_start` (Date, reqd), `items` (Table).
  Unique per (user, week_start), enforced in validate. Autoincrement naming.
- `CRM Rep Plan Item` (child): `activity_type` (Select Call/Meeting/Task/Email),
  `reference_doctype` + `reference_docname` (optional target), `planned_date` (reqd),
  `note`, `status` (Planned/Done/Missed, default Planned), `fulfilled_by_doctype` +
  `fulfilled_by`, `suggestion` (Link CRM Suggestion — provenance of proposed items).

- [ ] JSON + controllers, migrate, commit

### Task 2: Matching engine (`crm/rep_planning.py`) — TDD

- [ ] `crm/tests/test_rep_planning.py` pure tests first: kind mismatch never matches;
      reference mismatch never matches when the item names one; unreferenced item
      matches by kind+week; one actual fulfils one item (closest date wins); actual
      outside the week does not match; already-Done items are not rematched
- [ ] Pure `match_items(items, actuals)` returning `{item_name: actual}` assignments
- [ ] `match_actuals()` scheduler entry (daily): for plans of the current and previous
      week, batch-load actuals per user/kind, apply matches (`status=Done`,
      `fulfilled_by*`), mark items past their week with no match as `Missed`
- [ ] Integration test: plan + done task → item Done with fulfilment link; stale item → Missed
- [ ] Commit

### Task 3: API (`crm/api/rep_plan.py`) + propose-week + scheduler wiring

- [ ] `get_plan(week_start, user=None)` — own plan, or any plan for managers; includes
      plan-vs-actual rollup per activity type
- [ ] `save_plan(week_start, items)` — upsert own plan only (typed dicts, validated)
- [ ] `propose_week(week_start)` — drafts items from the caller's open suggestions
      (action → kind mapping, dates spread over the week's workdays, suggestion
      provenance). Returns drafts only — nothing is written until the rep saves,
      which is the Phase 8 write-gate rule applied to planning
- [ ] Endpoint tests: ownership, upsert idempotence, propose returns drafts without
      writing, accepting a proposed plan marks its suggestions Accepted
- [ ] `hooks.py` daily: `crm.rep_planning.match_actuals`
- [ ] Commit

### Task 4 (next slice): Planner UI

Week-grid page (rep view + manager roster), "Propose my week" button, manual override
of fulfilment. Rides the Phase 7 design system. Not in this slice.

## Verification

Server suites green (`crm.tests.test_rep_planning` + agent regression), frontend 142,
live smoke: propose → save → complete a task → `match_actuals` → item Done.
