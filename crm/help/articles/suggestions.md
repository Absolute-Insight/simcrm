---
title: The suggestions inbox
category: Proactive selling
order: 1
---

The suggestions inbox — the badge in the sidebar — is where Vectora proposes
your next actions. The system watches; you decide. Nothing here writes to a
record until you confirm it.

## What raises a suggestion

| Signal | Fires when |
|---|---|
| **Idle deal** | No activity logged on an open deal for a while |
| **No next step** | An open deal has no open task |
| **Lead SLA** | A new lead is untouched past the response target |
| **Close at risk** | The expected close date is near but the deal is still in an early stage |
| **Deal cooling** | The contact cadence on a deal is slowing against its own history — this fires *before* the idle threshold trips |
| **Stale plan** | A planned activity is past due with nothing logged against it |

The last two are the predictive ones: they warn before the problem is obvious.

## Working the inbox

- Suggestions are ranked by urgency. Reps see their own; managers also see
  unowned team-wide ones.
- **Accept** opens a pre-filled dialog showing exactly what will be created
  (usually a task or plan item). You confirm; then it exists.
- **Dismiss** asks why. The reason matters: a signal you keep dismissing backs
  off for longer each time, and dismissal statistics show your admin which
  thresholds the team keeps rejecting.

## Housekeeping you never have to do

- Only one open suggestion exists per signal per record — no pile-ups.
- Suggestions expire on their own after a while and dismissed ones observe a
  cooldown before the same signal can re-fire.

## Configuration

Admins tune the thresholds — idle days, close horizon, expiry and cooldown —
in **Settings → Assistant**, under Signals. Signals are deterministic and run
even when the model tier is off.
