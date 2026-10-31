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
- **A deal's probability follows its stage until someone sets it by hand.** Every
  weighted number reads `CRM Deal.probability`; it used to be written once at
  creation from the first stage's default, so the forecast never moved as deals
  advanced. On a status change a value still equal to the previous stage's
  default moves to the new stage's default; any other value was a decision and
  is kept. `closed_date` is stamped once on the way into Won and never
  overwritten.
- **Slip risk reads `expected_closure_date`, not `closed_date`.** `closed_date`
  is only set on a win, so anything scoring open deals against it can never
  fire.
- **Plan adherence counts only settled items** (planned date strictly before
  today), because fulfilment is written by a daily job — counting today's items
  would mark this morning's completed call as missed.
- **A settled month with nothing closed reports 0, not blank.** Only genuinely
  future months are null, so "zero pipeline" and "no data" stay distinguishable.
- **Cancellations are counted from the records and the plan, once.** A
  cancelled task or event fulfils nothing, so the matcher never sees it;
  `activity_cancellations` counts them directly. A plan item a rep marks
  **Cancelled** is not due: `plan_adherence` leaves it out of
  planned/done/missed (and so out of the adherence percentage) and adds it to
  `cancelled` instead, over the whole period. The planner also writes a
  Cancelled Visit event as such an item's `fulfilled_by`; that event is the same
  cancellation seen from the calendar, so `plan_adherence` asks
  `activity_cancellations(..., skip_plan_cancellations=True)` and counts it once.
- **Client reliability reaches an organization through the deal an activity
  references, or — for a calendar event — through an `Event Participants` row
  naming the organization,** which is how the visits a rep logs from the planner
  count without a deal. Activity on a lead is not counted — a lead's
  organization is free text. Sorted by rescheduled + cancelled, worst first.
- **Client reliability ignores the territory picker, like plan adherence and
  quota attainment, and is listed in `TERRITORY_BLIND` so the report says so.**

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

## Visit targets

`CRM Visit Target` is one row per rep: customer visits per **working week**
(planned or unplanned). Not monthly like quota, because MBP's managers talk in
visits a week. `crm.api.visit_targets.target_for(users, from, to)` pro-rates
it by the Monday-to-Friday days in the range (`visits_per_week x days / 5`), so
a month and a fortnight read against the same number. A rep with no row (or a
row of 0) has **no target**, which is reported as "No target", never as 0% or
as behind.

Managers set them in **Settings → Visit Targets** (`get_visit_targets` /
`set_visit_target`), with quota's guards reused from `crm.api.quota`: managers
only, their own subtree only, never their own row unless System Manager. 0 or
blank deletes the row. A rep sees their own row read-only.

**Visits against target** (`visits_by_rep`) counts plan items of a
`VISIT_KINDS` type (Visit, Unplanned Meeting) dated in the period: scheduled
(all of them), completed (Done), cancelled, missed, still planned. `target` is
the whole period's share; `target_to_date` the share already due, up to
**yesterday** (today is not settled, the same rule as adherence). "On track"
means completed ≥ target to date, so the 10th of the month does not read as
everyone behind. One row per rep in scope with a target or any visit.

**Activities by type** (`activities_by_type`) is the same status split per rep
and activity type, in the planner's type order.

## Customer interaction

`customer_interaction` returns **every CRM Organization**, the untouched ones
included. An interaction in the period is either a **Done plan item naming the
customer** (bucketed visits / deliveries / calls / emails / other by its type) or
a **completed calendar visit**: an Event in the Visit category, not Cancelled,
already started, with the organization as an Event Participant.

Completing a planned visit writes a Visit event as the item's `fulfilled_by`
(and the importer did the same for history), so the two overlap. An event that
records a Done item **which names its customer** is counted through the item
only. An event recording an item *without* a customer — history imported before
items had one — still counts, because it is the only place the customer is
named. Scope is by who did it: the plan's rep, the event's owner.

`last_interaction` is the latest such interaction on or before the period's end
**over all time**, with `last_rep` and `days_since` (to the period's end). Rows
sort fewest interactions first, then longest since the last (never first).
**Customers with no interaction** is the same function with `only_without=True`,
showing only the columns that can differ.

## Reports

Eleven built-ins, all registry entries over the metrics layer:
pipeline by stage, funnel conversion, plan adherence by rep, forecast vs actual,
pipeline by segment, quota attainment by rep, client reliability, visits against
target, activities by type, customer interaction, customers with no
interaction. The last four are territory-blind (rep plans have no territory;
customer interaction could narrow by the organization's territory and does not
yet), and all are schedulable as digests.

Registry strings are untranslated literals with `_()` applied **per request** —
a module is imported once per worker, so translating at import time would freeze
every label to the language of whoever made the first request.

A report declares `period: false` when it is a snapshot of this moment rather
than a window; the UI hides the date picker for those rather than showing a
control that changes nothing. None does today. Pipeline by stage takes the period
as "created in", and keeps a `get_snapshot_rows` for callers that mean the
pipeline right now: `get_report(..., snapshot=True)`, as digests and the
dashboard's panel do.

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

`CRM Report Digest` + `send_due_digests` (daily). The window is the previous
N *settled* days ending yesterday — one for a daily digest, seven for a weekly
one — because the job fires at midnight and `quota_in_period` pro-rates by
covered days: a window that reached into today charged an extra day of target
against nothing. Measures are formatted by the column type the registry
declares (money in the base currency, `%`, grouped integers), the same types
`formatCell` renders on the Reports page. Recipients must be enabled
Users holding a CRM role, at most `MAX_RECIPIENTS` (50) per digest, and each message is rendered inside
`frappe.set_user(recipient)` so the scope is the recipient's own: a rep gets
their rows, a manager the team's. All interpolated values are HTML-escaped.

## Key files

| File | Role |
|---|---|
| `crm/api/dashboard.py` | Every aggregate; the `CHARTS` registry the dispatcher resolves against |
| `crm/api/reports.py` | Report registry — consumption only |
| `crm/api/quota.py` | The rep × month admin grid |
| `crm/api/visit_targets.py` | Weekly visit targets: pro-ration and the Settings grid |
| `crm/fcrm/doctype/crm_visit_target/` | Visits per working week per rep |
| `crm/fcrm/doctype/crm_quota/` | Monthly target per rep |
| `crm/fcrm/doctype/crm_forecast_snapshot/` | Weekly forecast history, per rep and site-wide |
| `crm/fcrm/doctype/crm_report_digest/` | Scheduled email digests |
| `frontend/src/pages/Reports.vue` | Viewer, CSV export, print view |
| `frontend/src/utils/reportExport.js` | Pure cell formatting and CSV encoding (unit-tested) |
