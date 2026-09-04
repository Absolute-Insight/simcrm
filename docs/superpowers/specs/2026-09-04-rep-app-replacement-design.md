# Replacing MBP's rep app with Vectora — parity and gap design

**Date:** 2026-09-04
**Status:** drafted in session, pending review
**Context:** `mbp_reps.eml` (Bianca van der Westhuizen → Yield Group, 2026-08-24)
documents the app MBP's reps use today, with screenshots of every screen. The
decision is that Vectora replaces it outright, so this audits Vectora against
every capability in it and specifies what must be built to close the gap.

Companion to `2026-09-03-mbp-acumatica-import-design.md`, which supplies the
data. Neither is much use without the other: the import gives Vectora MBP's
customers and pipeline, this gives it MBP's daily workflow.

## Goal

A rep who used the old app on Friday can do everything they did, better, in
Vectora on Monday — and several things they could never do.

## What we are replacing

Read off the screenshots, not inferred. The app is a Firestore-backed visit
planner (its own reports name the `Scheduled_Activity_new` collection) with ten
menu items: Dashboard, New Lead, Plan an Activity, Unplanned Meeting, Manage
Open Activity, My Calendar, My Insights, Contact Support (disabled), Settings,
Admin View.

**It is genuinely in use.** The Admin View's charts cover Jul 26 – Aug 24 2026
and show roughly 439 activities scheduled across eight reps, Tamryn Barnard alone
at 123 scheduled / 94 completed. This is not a dead system being swept aside; it
is a live workflow with real adoption, and a replacement that loses any of it
will be felt immediately.

Its defining limit is stated by Bianca twice, and it is the reason we are here:
**"the app is not linked to Acumatica."** It knows about visits and nothing about
money. Her two feature requests both ask for the thing it structurally cannot
have — *"more statistics such as sales, quotes, values, budgets"* on the
dashboard, and *"more statistics as discussed in the meeting"* on the admin view.

## Where Vectora already wins

Not parity items — reasons the replacement is an upgrade rather than a lateral
move. Each is already built and tested.

**Completion is computed, not self-reported.** The old app asks the rep to go
back and close their own calls, and its dashboard measures whether they
remembered. Vectora's daily matcher (`crm/rep_planning.py`) resolves each planned
item against the call log, sent email, calendar event or task that actually
happened, and re-derives the whole horizon every run — so deleting the call
behind an item takes its Done away again. `.pi/feats/planning/README.md` puts it
plainly: plan-vs-actual is *"computed, never self-reported — that is the whole
point of the feature."* This alone answers the "Missed Activities … oldest is 125
days late" banner on Bianca's own dashboard.

**One tested source of numbers.** `crm/api/reports.py` contains no aggregation;
tiles and reports call the same function in `crm.api.dashboard`, and tests assert
they agree (`test_quota.py::test_the_report_and_the_tile_agree`). Two screens
cannot disagree about the same question.

**Money is handled properly.** Every monetary aggregate multiplies by the deal's
`exchange_rate` before summing, so MBP's 30 USD orders never get added to rands.
The old app has no money in it at all.

**Scoping follows the sales hierarchy**, not a role flag — a manager sees exactly
their subtree, and the rep picker never offers a row that would 403.

**Forecast accuracy is measured against reality** — the last snapshot taken
*before* a month began, compared to that month's actual.

**Quota is pro-rated by covered days**, so a week of revenue is never compared
against a month's target.

**Proactive, not just retrospective.** Suggestions, deal health and "needs
attention" have no counterpart in the old app, which can only tell you what you
already did.

**The AI is not a black box.** The old app's "Dynamic AI Insights" sends the
activity set to a model and prints prose. Vectora's Analyst puts the model's
narrative *beside the computed tables it was derived from*. Worth knowing: AI is
**not** our differentiator here — they already have one and have seen the trick.
Verifiability is.

## Parity audit

| Old app | Vectora today | Verdict |
|---|---|---|
| Dashboard — missed-activity banner | Suggestions inbox + Dashboard | ✅ better |
| Dashboard — This Week's Schedule strip | `Planner.vue` week grid, plan vs actual | ✅ better |
| Dashboard — 12 monthly activity donuts | — | **deliberately not rebuilt**, see below |
| Dashboard — *"sales, quotes, values, budgets"* | Won/ongoing deals, avg deal value, time-to-close, sales trend, forecast vs actual, quota attainment | ✅ **the whole point** |
| New Lead | `CRM Lead` + Contacts | ⚠️ field gaps — G9 |
| Plan an Activity | Planner + `CRM Task` + `Event` | ⚠️ vocabulary — G1, G6 |
| Unplanned Meeting | — | ❌ **G2** |
| Manage Open Activity | `Tasks.vue` + Planner | ✅ |
| Reschedule / Complete / Cancel | `CRM Task` status has no Rescheduled | ⚠️ **G3** |
| Cannot close without comments | not enforced | ❌ **G4** |
| Activity History (edit trail + notes) | Frappe versions exist, not surfaced | ⚠️ **G7** |
| My Calendar | `Calendar.vue`, day/week/month | ✅ better |
| My Insights — activity table + CSV | Task views + `Reports.vue` CSV export | ✅ |
| My Insights — **Client Reliability** | — | ❌ **G5** |
| Admin — Company & Contact Manager | Organizations + Contacts | ⚠️ sub-code search — G6 |
| Admin — Add Company, User Management | Organizations + Settings | ✅ |
| Admin — Dynamic AI Insights | `Analyst.vue` | ✅ better |
| Admin — User Productivity / Completions | Plan adherence by rep report | ✅ |
| Admin — User **Cancellations** | not counted | ⚠️ **G8** |
| Admin — Detailed report by event/creation date | Reports + date pickers | ✅ |

### What we deliberately do not rebuild

**The wall of monthly activity donuts.** Bianca's own dashboard shows twelve
tiles, nine of them reading "No Activity", and a year total of 4. It is a chart
of whether someone remembered to tick a box. Vectora replaces the *question*:
the dashboard shows money and the planner shows adherence, both computed. If MBP
asks for the donuts specifically we can add an activity-mix tile, but proposing
it would be rebuilding the weakest screen in the product we are replacing.

## The gaps

Nine, none architectural. Vectora already has the hard half — computed
fulfilment, hierarchy scoping, quota, forecasting. These are modelling and
surface work.

**G1 — "Visit" as a first-class activity type.** *The most important item here.*
`CRM Rep Plan Item.activity_type` offers Call, Meeting, Task, Email. MBP's reps
do not think in those; their unit of work is a **customer visit to a plant or a
mine**, and the old app's types are Visit / Unplanned Meeting / E-Mail. Add
`Visit` to the Select and to `ACTUAL_SOURCES` in `crm/rep_planning.py`, sourced
from `Event` the way Meeting already is. Getting this vocabulary right matters
more to adoption than any chart on this list.

**G2 — Log an unplanned visit.** Their words: *"in the event a rep is called to
site for a break down as it was not a planned visit."* A retrospective flow that
records what happened and marks it done in one step — creates the `Event` and a
plan item already fulfilled, with `manual_override` set so the daily matcher
leaves it alone. The override machinery exists; this is a flow over it.

**G3 — Rescheduled as a real status.** `CRM Task` has Backlog / Todo / In
Progress / Done / Canceled. A rescheduled visit is neither done nor cancelled,
and treating it as either loses the fact that the *client* moved it — which is
exactly what G5 measures. Add it, and keep the original date in history.

**G4 — A note is required to close an activity.** *"The app does not allow you to
close the call without comments."* This is the discipline that makes their
activity history worth reading, and it is a hard requirement — losing it would be
a visible regression on day one. Enforce in `validate` on the transition into a
closed status, not in the UI alone.

**G5 — Client Reliability.** Activity statuses grouped by client, sorted by most
rescheduled and cancelled. Nothing in Vectora groups activity by organization
this way, and it is a genuinely good idea: it turns admin exhaust into a signal
about which customers waste the team's time. Per the reporting rule, the
aggregate goes in `crm/api/dashboard.py` and the report registry consumes it —
`crm/api/reports.py` must not aggregate. Depends on G3, since "rescheduled" has
to exist before it can be counted.

**G6 — Search by customer / sub-code.** Both the Company & Contact Manager and
Plan an Activity search on *"Customer or Sub Code"* — the `C-IMP003E` identifier.
Reps know their accounts by that code. Organization search must match on
`acumatica_id`, which the import spec's Prerequisite 1 creates.

This gap changes what that custom field *is*. Until now `acumatica_id` has been
sync bookkeeping, and an absent one is invisible — nothing user-facing reads it.
Make it a search key and its absence stops being invisible and starts being
**silent**: a rep types `C-IMP003E` on a site that never had the field created
and gets an empty result set, not an error. That reads as "search is broken",
which is the worst way for a missing-schema problem to surface, and it will be
reported as a search bug rather than a setup one.

So G6 carries two requirements beyond the search itself. The field's absence must
be **detected and surfaced** rather than degrading to no results — a search by
code on a site without the column says so.

That detection is a null check, not a schema-introspection layer, and the spec
says so explicitly because the requirement reads heavier than it is.
`frappe.get_meta("CRM Organization").get_field("acumatica_id")` returning `None`
is a sufficient and reliable probe at the top of the search handler. Verified
against the framework: `create_custom_fields` collects every doctype it actually
changed and ends with `frappe.clear_cache(doctype=...)` **and**
`frappe.db.updatedb(doctype)` for each — the meta cache and the DDL are
synchronised in the same loop, so meta cannot be stale behind the column. A
doctype it did not change is absent from that set, but then meta already matched
reality. No manual cache clear, no `information_schema` query. And G6 must not ship with an
undocumented manual precondition, which is the argument for fixing
[#166](https://github.com/Absolute-Insight/simcrm/issues/166) by separating
schema install from activation rather than by adding an on-disable path: the
first makes the direct `ensure_custom_fields()` call unnecessary, the second only
makes it reversible. **Worth deciding before G6 is built, not after.**

**G7 — Surface the activity's edit history.** Frappe already records it; the old
app shows it inline in the edit dialog alongside the note that accompanied each
change. Surface the existing versions rather than building a parallel log.

**G8 — Count cancellations per rep.** `plan_adherence(..., group_by_user=True)`
returns planned / done / missed. Add cancelled so the manager view answers what
their User Cancellations chart answers.

**G9 — Lead form field parity.** Their form captures **birthday**, **contact
type** and a **province** picker; `CRM Lead` has none of the three. Birthday is
relationship-selling ammunition a rep will notice missing.

## Sequencing

The two specs interlock, and the order is forced by dependencies rather than
preference.

1. **Import first** (the other spec). G6 needs `acumatica_id` to exist; the whole
   value proposition — money on the dashboard — needs deals in the site.
2. **G1, G3, G4** next. Vocabulary and discipline. These change the data model,
   so they must land before reps generate history under the old shape.
3. **G2, G7, G9.** Surfaces over models that now exist.
4. **G5, G8.** Reporting, last, because G5 depends on G3 having accumulated real
   rescheduled rows to be worth looking at.

**Contacts are on the critical path for all of it.** A visit is to a *person*.
The import spec establishes that the rep app holds contacts joined by customer
sub-code — that export is what makes G1 and G2 mean anything.

## Risks

**Adoption, not features.** Eight reps have muscle memory in an app whose home
screen is their week. If Vectora's first screen is a pipeline dashboard, a rep
looking for "what am I doing Tuesday" has to learn a new route on day one.
Recommendation: the rep-role landing page is the Planner, not the Dashboard.

**Feature-for-feature parity is the wrong target for one item.** The monthly
donut wall should not be rebuilt (above). Every other line in the audit should
be honoured, including the ones that look small — G4 especially, because it is
the habit their history depends on.

**The old app's data is not migrated by either spec.** Activity history lives in
Firestore. Whether reps start clean or bring their history across is an open
question for MBP, and if it comes across it is a third import with its own
mapping. Not scoped here.

## Testing

Following the repo convention that pure logic is unit-tested:

- `match_items` gains Visit cases — a visit matched from an `Event`, and a visit
  with no event going Missed.
- The close-note rule is tested at the model, not the component: closing without
  a note raises; closing with one saves; a status change between two open states
  is unaffected.
- Client Reliability is tested for tile/report agreement, the pattern
  `test_the_grouped_reads_agree_with_the_per_rep_ones` already establishes.
- Cancellation counts must not change existing adherence numbers — a regression
  test on `plan_adherence` before and after.
- G6 on a site **without** `acumatica_id`: a code search must surface the missing
  column, not return an empty list. This is the case that will otherwise reach a
  user as a phantom search bug.
