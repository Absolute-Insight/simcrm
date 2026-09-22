# Rep planning

> Reps plan the week's concrete activity; the agent can draft it from the
> suggestion queue; the daily matcher resolves each planned item against the
> activity that actually happened. Plan-vs-actual is **computed, never
> self-reported** — that is the whole point of the feature.

## What the user sees

- **Planner** (`/crm/planner`): a Monday-based week grid, one column per day.
  Add, edit, reschedule and remove items; a header rollup of planned / done /
  missed.
- **"Propose my week"**: drafts a week from the rep's open suggestions. It
  writes nothing — the rep reviews and saves, which is the Phase 8 write gate
  applied to planning.
- **Managers** see the reps they are allowed to see (sales hierarchy, not just
  role) and can read a plan, never rewrite someone else's week.

## Model

- `CRM Rep Plan` — one per `(user, Monday)`. Enforced by a **unique index**
  (`unique_user_week`, added in `on_doctype_update`), not by a read-then-throw
  in `validate`, because two concurrent first saves both passed that check.
- `CRM Rep Plan Item` (child) — activity type, planned date, note, optional
  Deal/Lead reference, and the fulfilment link the matcher writes
  (`fulfilled_by_doctype`, `fulfilled_by`, `status`).
- `manual_override` — set when a rep corrects an item by hand. The daily job
  never touches an overridden row.

Concrete items are the source of truth; rollups are derived, so "planned 30
calls" and the 30 planned call items can never disagree.

A **Rescheduled** task is still open: it needs a new due date and stays in every
"open task" query until it is Done or Canceled. Moving a task to Rescheduled —
on the board, on the form, or from the status menu in a record's task list — asks
for the closing note and the new date, the same as the two statuses that do end
it. The three surfaces share one helper (`frontend/src/utils/taskClosing.js`)
so they cannot drift. `crm_task.NOTE_REQUIRED_STATUSES` is
the list that must say why; `TERMINAL_STATUSES` is the shorter list that ends
the task, and it is the one the open-task queries filter on.

## Matching

`crm/rep_planning.py`. `match_items` is pure: item rows and actual rows in, an
`{item: actual}` assignment out. Ranking is `(on-reference first, smallest date
delta, then name)` — the tie-break is deterministic so a rerun cannot reshuffle.
An actual can be claimed by **at most one item, ever**.

Where each activity's actuals come from is a table (`ACTUAL_SOURCES`), not an
`if` chain, because each kind gets it wrong differently:

| Activity | Source | Keyed on | Filtered by |
|---|---|---|---|
| Task | `CRM Task` | `modified` (no completion timestamp exists) | `status = Done` |
| Call | `CRM Call Log` | `start_time`, falling back to `creation` | `status = Completed`, matched on **caller or receiver** — a telephony log is owned by the integration user, not the rep |
| Email | `Communication` | `creation` | `Sent` + `communication_type = Communication` + `medium = Email` |
| Meeting | `Event` | start time | not `Cancelled`; **keeps its reference** |
| Visit | `Event` | `starts_on` | `event_category = "Visit"`, not `Cancelled` |

A visit and a meeting are both calendar events; the category tells them apart.
"Visit" is added to `Event.event_category` by a Property Setter
(`ensure_visit_event_category`), and Meeting excludes it, so one event is
emitted under exactly one kind. Frappe stores the first option ("Event") for
any event saved without a category, so every existing event stays a Meeting.
`log_unplanned_visit` records a visit that was never planned — a rep called
to site for a breakdown — as an Event in that category plus a plan item
already Done and flagged `manual_override`, in one call.

Every run re-derives the whole horizon instead of appending to it, so deleting
the call behind an item takes its Done away again and `Missed` is a verdict the
run reached rather than a state the item is stuck in. Items older than
`MATCH_HORIZON_WEEKS` are swept to Missed and the week becomes read-only.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `get_plan(week_start, user?)` | The week, its items, a rollup, and a `modified` token |
| `save_plan(week_start, items, modified?)` | Upsert. Send `modified` back for optimistic concurrency (raises `TimestampMismatchError`); send surviving rows **with their `name`** so a reschedule keeps matcher state and its suggestion link |
| `propose_week(week_start)` | Drafts from open suggestions, spread over the *remaining* weekdays. Writes nothing |
| `mark_fulfilled(item, ...)` / `mark_missed(item)` / `clear_override(item)` | Manual override; the matcher then leaves the row alone. A named fulfilment record is verified — it must exist, satisfy its kind's status filters, and belong to the caller |
| `get_visible_reps()` | Exactly the reps whose plans the caller may open |
| `log_unplanned_visit(organization, note, when?, reference?)` | The Event and the fulfilled, overridden item, in one step. A note is required — closing anything without saying why is the habit the old rep app enforced and the one reps notice first |

## Scheduling

`crm.rep_planning.match_actuals` — daily. Per-plan savepoint isolation and a
commit per plan (skipped under test), so one bad plan cannot abort the run; a
plan's claims on records are merged into the run's `claimed` set only when it
succeeds. Every rep's activity over the whole horizon is fetched once per
source (`_actuals_by_user`, four queries a run) and sliced per plan, so the
query count does not grow with the number of plans.

## Permissions

`visible_users()` in the doctype controller follows the **CRM Sales Hierarchy**
that already scopes Leads and Deals: own always, subtree when the hierarchy is
enabled and the user is in it, everything for System Manager and an out-of-tree
Sales Manager. It backs the permission query, `has_permission`, `get_plan`'s
check and the rep picker — so the picker never offers a row that would 403.

A plan is only ever *written* by its own rep, at both doors, and it is never
handed to another user: `validate` refuses a change of `user` on an existing
plan, and `has_permission` compares against the stored owner rather than the
in-memory document (frappe checks write permission after `set_value` has applied
the caller's changes, so a rewritten `user` used to look like the owner).

## Importing the old rep app's history

`crm/integrations/repapp/history.py`. MBP's reps kept their activity in a
Firestore visit planner before Vectora; its per-rep export
(`report_<First>_<Last>_<date>.csv`, one row per activity: company, contact,
type, date, note, status, rep code) is the history the rep-app spec left as
"a third import with its own mapping". In MBP's vocabulary every row is a
"call"; only `Phone Call` rows are telephone calls.

| Export | Becomes |
|---|---|
| `Visit`, `Unplanned Meeting` | plan item `Visit`; **Completed / Canceled** also get an `Event` (category Visit, status Completed / Cancelled, the organization and matched contact as participants, the rep as owner, the full note as description) — the record the matcher, `client_reliability` and `activity_cancellations` count |
| `Phone Call`, `WhatsApp` | plan item `Call`, done on the rep's word (no number to hang a Call Log on) |
| `E-Mail` | plan item `Email`, likewise |
| `Completed` | item `Done`, `manual_override` |
| `Canceled` | item `Missed`, `manual_override`, no fulfilment |
| `Scheduled`, `Rescheduled` | item `Planned`, **not** overridden — a live item the matcher and the horizon sweep treat like anything planned from now on |

The item's one-line note is the old app's `--- Conclusion ---` when there is
one (the text above it is the plan, the conclusion is what happened); the
event keeps the whole note. `date` (dd/mm/yyyy HH:MM, site-local) is the only
timestamp used; the export's UTC `completedAt` is the planned slot again in
most rows and is ignored.

Company names are free text — "Impala - Shaft 14", "Harmony Avgold Limited" —
and only a third match an organization exactly, so the run takes a reviewed
`company-map.json` (`{"old name": "CRM Organization name" | null}`).
`build_company_map` drafts it from the site's organizations (normalised exact
matches filled, `company-map-candidates.json` for the rest). An unmapped row is
still imported, named in the event subject, and reported — nothing the client
sent is dropped. Contacts are matched on the whole name among the
organization's contacts.

```bash
P=/home/frappe/frappe-bench/sites/<site>/private/files/mbp/calls   # CSVs + owners.json ({"032-IO": "rep@..."})
bench --site <site> execute crm.integrations.repapp.history.build_company_map --kwargs '{"reports_dir": "'$P'"}'
#   review $P/company-map.json against $P/company-map-candidates.json, then:
bench --site <site> execute crm.integrations.repapp.history.import_history \
  --kwargs '{"reports_dir": "'$P'", "owners": "'$P'/owners.json", "dry_run": true}'
bench --site <site> execute crm.integrations.repapp.history.import_history \
  --kwargs '{"reports_dir": "'$P'", "owners": "'$P'/owners.json"}'
```

A dry run does all the work and rolls back, so its counts, rejects and
unmapped-company list are real. The real run writes `history-manifest.json`
beside the CSVs (Firestore id → plan item and event) and skips those ids next
time, so a re-run with a corrected map or a later export appends only what is
new. Events are inserted as the rep (`frappe.set_user`) because frappe stamps
`owner` from the session and every report credits an event to its owner;
`send_reminder` is off so the daily event digest never mails a rep about a
visit that happened in March.

## Key files

| File | Role |
|---|---|
| `crm/rep_planning.py` | Pure matcher + the daily job |
| `crm/integrations/repapp/history.py` | One-shot import of the old rep app's activity export into plan items + visit events |
| `crm/api/rep_plan.py` | Endpoints, concurrency token, manual override |
| `crm/fcrm/doctype/crm_rep_plan/crm_rep_plan.py` | Hierarchy visibility, unique index |
| `frontend/src/pages/Planner.vue` | The week grid |
| `frontend/src/utils/planner.js` | Pure week/rollup helpers (unit-tested) |
