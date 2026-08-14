# Phase 11 — Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean, informative reporting as pure consumption of the metrics layer: four built-in reports with a tabular viewer, CSV export, print stylesheet, and scheduled email digests. No custom-report builder until these prove the layer (PLAN.md rule).

**Architecture:** A registry in `crm/api/reports.py` maps report keys to row-producing functions (columns + rows shape, shared date/user filters). The viewer is one page rendering any registry report. Digests are a small doctype + scheduler job that renders the same rows into an email table — one source of numbers throughout.

**Spec:** `.pi/PLAN.md` § Phase 11.

## Built-in reports

| Key | Rows | Source |
|---|---|---|
| `pipeline_by_stage` | stage, deals, total value, weighted value | direct qb over CRM Deal × Status |
| `funnel_conversion` | stage, count, conversion % | `get_funnel_conversion` data |
| `plan_adherence_by_rep` | user, planned (due), done, missed, adherence % | CRM Rep Plan items |
| `forecast_vs_actual` | month, forecasted, actual | `get_forecasted_revenue` data |

### Task 1: Registry + API (TDD)

- [ ] `crm/tests/test_reports.py` first: each report returns its declared columns and
      row shape; user scoping; unknown key throws; adherence math matches metrics
- [ ] `crm/api/reports.py` — `REPORTS` registry, `list_reports()`, `get_report(name,
      from_date, to_date, user)` (whitelisted, sales-user gated)
- [ ] Commit

### Task 2: Digest doctype + job (TDD)

- [ ] `CRM Report Digest` doctype: report (Select of registry keys), recipients
      (Small Text, comma emails), frequency (Weekly/Daily), enabled
- [ ] `send_due_digests()` scheduler entry (daily; weekly rows fire on Mondays) —
      renders report rows into a simple branded HTML table via `frappe.sendmail`
- [ ] Test: enabled digest queues an email with the report title in subject; disabled
      does not
- [ ] Commit

### Task 3: Reports page

- [ ] `/crm/reports` route + sidebar entry ("Reports", lucide file-bar-chart icon)
- [ ] Page: report picker (left rail or select), date range + user filter, table
      (sticky header, tabular numerals), Export CSV (client-side blob), print
      stylesheet (`@media print`: hide chrome, table only)
- [ ] Live verify + screenshot; commit

## Verification

Server suites green; frontend 142; live: open each report, export a CSV, print preview.
