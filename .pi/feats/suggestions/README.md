# Proactive suggestions

> The surface that makes Vectora proactive rather than reactive: the system
> watches, predicts, and proposes; the rep confirms. Nothing here writes to a
> record without a human pressing a button.

## What the user sees

- **Inbox panel** in the app shell, with a count badge. Opens to the open
  suggestions for the signed-in rep (managers see unowned team-wide ones too),
  ranked by urgency.
- **"Needs attention" section** on a Deal, showing the deal-health score with
  the named factors that produced it — never a bare number.
- **Accept** opens a pre-filled confirm dialog showing exactly what will be
  created. **Dismiss** asks why, and the answer is load-bearing (see below).

## The two tiers, and why they are separate

**Deterministic (always on).** Signals and scoring are computed from structured
data — dates, stage, task and message counts. They work with the agent tier
switched off, and no model output can influence them. This is a hard
constraint from the live-model injection gate: see [../agent/README.md](../agent/README.md).

**Model-assisted (optional, off by default).** Thread summaries and reply
drafts. Every model output is untrusted input: it is shown to a human in a
compose window and is never written anywhere by the server.

## Signals

`crm/agent/signals.py`. Each detector is a pure function over plain rows, so it
is unit-testable without a site; a thin frappe layer batches the queries that
feed them.

| Signal | Fires when | Backward or forward looking |
|---|---|---|
| `idle_deal` | No activity logged for `IDLE_DEAL_DAYS` | backward |
| `no_next_step` | Open deal with no open task | backward |
| `lead_sla` | New lead untouched past the response target | backward |
| `close_at_risk` | Expected close date approaching while the stage probability is still below `EARLY_STAGE_PROBABILITY` | **forward** |
| `deal_cooling` | Contact cadence decelerating against this deal's own median gap, before the flat idle threshold trips | **forward** |
| `stale_plan` | A plan item is past due with no linked activity | backward |

The last two are what "predictive, not reactive" means concretely: they fire
*before* the threshold everyone else measures after.

## Prediction

`crm/agent/predict.py`. `score_deal(features)` starts at 100 and subtracts named,
weighted factors; every factor ships `{key, label, weight}` and the UI renders
the labels. Weights are module constants, not magic numbers inline.

Forward-looking factors: `slow_stage` (time in this stage vs the historical
median for that same stage, suppressed below 5 samples), `slip_risk` (expected
close date near while probability is low), `cooling` (cadence decelerating).

## Dedupe, cooldown and expiry

One open suggestion per `(signal, reference)`. A dismissed or accepted signal is
suppressed for a cooldown; **the cooldown stretches for a repeat dismisser**, up
to `MAX_COOLDOWN_MULTIPLIER`. Expired rows get their own shorter cooldown so the
job cannot expire and immediately re-create the same row. `purge_old_suggestions`
sweeps daily — expired, dismissed *and accepted* rows past `PURGE_AFTER_DAYS` —
keeping anything a plan item still links to. Suggestions raised by an automation
rule carry the same `expires_on` (`suggestion_ttl_days`) and the same 140-char title
clip as the hourly signals.

Dismissal reasons are readable through `get_dismissal_stats`, so a threshold that
reps keep rejecting is visible rather than guessed at.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `crm.api.suggestions.get_suggestions(reference_doctype?, reference_docname?)` | Open suggestions, owner-scoped; a reference narrows to one record and is permission-checked against that record |
| `crm.api.suggestions.get_open_count()` | Badge count, scoped identically (through `get_list`, so the doctype's permission query applies — a hierarchy-scoped manager is badged with their subtree, not the site) |
| `crm.api.suggestions.get_dismissal_stats(user?)` | Dismissals per signal, with reasons |
| `crm.api.suggestions.accept(name)` / `dismiss(name, reason?)` | Flip status only — the record an acceptance leads to is created client-side behind the confirm dialog |
| `crm.agent.api.summarise_thread(...)` / `draft_reply(...)` | Model tier, rate-limited, degrade cleanly when disabled |

## Scheduling and realtime

- `crm.agent.signals.run_signals` — hourly. Per-candidate savepoint isolation, so
  one bad row costs its own row and not the run.
- `crm.agent.signals.purge_old_suggestions` — daily.
- New suggestions publish `crm_suggestion` over the socket, **once per affected
  user per run** with an empty payload; the client refetches through the scoped
  endpoint so nothing crosses a permission boundary over the wire.

## Permissions

Ownership is enforced twice on purpose: in the endpoints (which save with
`ignore_permissions` because the state machine is theirs) and on the doctype via
`get_permission_query_conditions` + `has_permission`, because
`frappe.client.get_list` is a second door into the same table. `crm/tests/test_row_permissions.py`
knocks on that second door specifically. `accept`/`dismiss` use the doctype's own
`has_permission` (hierarchy-aware via `visible_users()`) rather than a flat "is a
manager" test, so an orphaned suggestion — whose record is gone and therefore skips
the record-access check — cannot be cleared by a manager outside its subtree.

## Configuration

`CRM Agent Settings` → Signals section: `signals_enabled`, `idle_deal_days`,
`close_horizon_days`, `suggestion_ttl_days`, `dismiss_cooldown_days`.

## Key files

| File | Role |
|---|---|
| `crm/agent/signals.py` | Detectors, dedupe, the hourly runner, realtime publish |
| `crm/agent/predict.py` | Explainable scoring and factor attribution |
| `crm/api/suggestions.py` | Inbox endpoints |
| `crm/automation.py` | Deterministic rules that can also raise suggestions |
| `frontend/src/components/Suggestions.vue` | The shell inbox panel |
| `frontend/src/components/RecordSuggestions.vue` | Per-record "Needs attention" |
| `frontend/src/stores/suggestions.js` | Store, badge, accept/dismiss flows |
