---
title: Deal health
category: Proactive selling
order: 2
---

Every open deal has a health score, shown in the **Needs attention** section
of the deal page and behind the **Critical deals** count on the dashboard.

## How the score works

The score starts at 100 and subtracts a weighted amount for each named risk
factor present. Every factor is shown with its label — the score is never a
bare number you have to guess at.

Factors include:

- **Idle** — days since the last logged activity.
- **No next step** — no open task on the deal.
- **Slow stage** — the deal has been in its current stage longer than the
  historical median for that stage (only measured once enough history exists).
- **Slip risk** — the expected close date is near while the stage probability
  is still low.
- **Cooling** — the contact cadence is decelerating against the deal's own
  median gap.

## Reading it

- A low score is a prompt to look, not a verdict. The factors tell you what to
  fix: log the call you made, set the next task, or move the date honestly.
- The score is computed from structured data only — dates, stages, task and
  message counts. It does not depend on the model tier and no model output can
  influence it.

## Where it shows up

- The deal page's **Needs attention** section — score plus factors.
- The dashboard's **Critical deals** tile counts deals whose score is below
  the risk threshold.
- Several factors also raise suggestions in the inbox, so the same risk is
  visible where you plan your day.
