# Analytics, forecasting and reporting

> One tested source of numbers. Dashboards, forecasts and reports all consume
> `crm/api/dashboard.py`; a report that computed its own aggregate is how two
> surfaces come to show different values for the same question, so reports may
> not do it.

## The rule, stated precisely

`crm/api/reports.py` contains **no aggregation**. Where a report needs a
different shape from a tile, the shared function in `crm.api.dashboard` grows a
parameter and both call sites pass it — for example `pipeline_by_stage(...,
status_types, date_field)` and `plan_adherence(..., group_by_user=True)`.
Tests assert the tile and the corresponding report row are equal for the same
period; `crm/tests/test_quota.py::test_the_report_and_the_tile_agree` is the
pattern.

## Correctness decisions worth knowing

- **Currency.** Every monetary aggregate multiplies by the deal's stored
  `exchange_rate` before summing, so nothing ever adds two currencies together.
  `get_base_currency()` is the single definition of what "the" currency is.
- **The forecast excludes Lost deals entirely.** They previously counted at
  100% of expected value, which inflated every forecast and every snapshot
  taken from one. A patch clears the contaminated snapshot history.
- **"Actual" revenue is bucketed by `closed_date`**, the month a deal actually
  closed — not by the month it was *expected* to close.
- **Slip risk reads `expected_closure_date`, not `closed_date`.** `closed_date`
  is only set on a win, so anything scoring open deals against it can never
  fire.
- **Plan adherence counts only settled items** (planned date strictly before
  today), because fulfilment is written by a daily job — counting today's items
  would mark this morning's completed call as missed.
- **A settled month with nothing closed reports 0, not blank.** Only genuinely
  future months are null, so "zero pipeline" and "no data" stay distinguishable.

## Scoping

Aggregates are hand-built queries, so frappe's `permission_query_conditions`
hook never reaches them. `scope_deals()` / `scope_leads()` apply the same
criterion the hook builds, and `visible_reps()` does the user-keyed equivalent
for plan and quota aggregates — so a manager's rep table and their deal tiles
cover the same people.

## Quota

`CRM Quota` is monthly per rep in the base currency; quarter, year and team
numbers are sums over those rows and are never stored, so a team target cannot
disagree with the reps' underneath it. The document name is built from
`(user, period_start)`, so the primary key enforces one target per rep-month,
and a mid-month date snaps to the first of that month in `before_naming` (the
name is built before `validate` runs).

An arbitrary dashboard range is **pro-rated by covered days**: a full month
returns exactly that month's quota, a quarter three, a week a week's worth.
Comparing a week of revenue against a whole month's target would not be
attainment.

Managers set targets in **Settings → Sales Targets** (a rep × month grid with a
"fill year" shortcut); reps see their own row read-only.

## Reports

Five built-ins, all registry entries over the metrics layer:
pipeline by stage, funnel conversion, plan adherence by rep, forecast vs actual,
quota attainment by rep.

Registry strings are untranslated literals with `_()` applied **per request** —
a module is imported once per worker, so translating at import time would freeze
every label to the language of whoever made the first request.

A report declares `period: false` when it is a snapshot of this moment rather
than a window (the open pipeline); the UI hides the date picker for those rather
than showing a control that changes nothing.

## Reading many reps at once

`won_value_in_period` / `quota_in_period` answer for one rep (the tile).
`won_value_by_user(users, …)` / `quota_by_user(users, …)` answer for a list in
a fixed number of queries, and are what the quota report and the Sales
Targets grid consume — a grid of fifty reps is not a hundred queries. Same
definition of belonging (owned or assigned), so the grouped and per-rep
answers are equal; `test_the_grouped_reads_agree_with_the_per_rep_ones` pins
that.

## Forecast accuracy

`take_forecast_snapshot` (weekly) stores the forecast per month, per rep and
site-wide. Each scope is written under its own savepoint and committed on its
own, so one rep's failure is logged and costs that scope's rows only. The
table carries a unique `(snapshot_date, month, scope, user)` key; Site and
Team rows store `user` as `''` rather than NULL because a unique index does
not dedupe NULLs. `get_forecast_accuracy` compares the last snapshot taken *before* a
month began against that month's live actual — measured against reality, not
against what the snapshot believed at the time.

## Scheduled digests

`CRM Report Digest` + `send_due_digests` (daily). Recipients must be enabled
Users holding a CRM role, at most `MAX_RECIPIENTS` (50) per digest, and each message is rendered inside
`frappe.set_user(recipient)` so the scope is the recipient's own: a rep gets
their rows, a manager the team's. All interpolated values are HTML-escaped.

## Key files

| File | Role |
|---|---|
| `crm/api/dashboard.py` | Every aggregate; the `CHARTS` registry the dispatcher resolves against |
| `crm/api/reports.py` | Report registry — consumption only |
| `crm/api/quota.py` | The rep × month admin grid |
| `crm/fcrm/doctype/crm_quota/` | Monthly target per rep |
| `crm/fcrm/doctype/crm_forecast_snapshot/` | Weekly forecast history, per rep and site-wide |
| `crm/fcrm/doctype/crm_report_digest/` | Scheduled email digests |
| `frontend/src/pages/Reports.vue` | Viewer, CSV export, print view |
| `frontend/src/utils/reportExport.js` | Pure cell formatting and CSV encoding (unit-tested) |
