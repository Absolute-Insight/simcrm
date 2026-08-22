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
- **Stage stagnation**, **close date passed** and **one-sided** (you are the
  only one talking) round out the list.

A factor that cannot be measured is never punished: a deal with no expected
close date does not lose points for not having one.

## The bands

| Band | Score |
|---|---|
| **Healthy** | 70–100 |
| **At risk** | 40–69 — one or more factors firing; look at the list |
| **Critical** | below 40 — several are; where a manager should be asking |

## Reading it

- A low score is a prompt to look, not a verdict. The factors tell you what to
  fix: log the call you made, set the next task, or move the date honestly.
- The score is computed from structured data only — dates, stages, task and
  message counts. It does not depend on the model tier and no model output can
  influence it.
- It is not a probability of closing — stage probability is that. Health
  measures whether the deal is being *worked*, which is the question you can
  do something about today.

## Where it shows up

- The deal page's **Needs attention** section — score plus factors.
- The dashboard's **Critical deals** tile counts deals whose score is below
  the risk threshold.
- Several factors also raise suggestions in the inbox, so the same risk is
  visible where you plan your day.
