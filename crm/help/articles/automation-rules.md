---
title: Automation rules
category: Proactive selling
order: 4
---

Automation rules are deterministic if-this-then-that rules an admin defines in
**Settings → Automation Rules**. They run on record changes and never depend
on the model tier — a rule fires the same way every time, model on or off.

## What a rule is

- **A trigger** — the record event the rule watches.
- **Conditions** — what must be true of the record for the rule to apply.
- **An action** — what happens: update a field, or raise a suggestion in the
  owner's inbox.

## Rules vs. signals

The built-in signals (idle deal, no next step, close at risk…) are Vectora's
own opinionated detectors, tuned in **Settings → Assistant**. Automation rules
are yours: site-specific policy like "when a deal moves to Negotiation, raise
a reminder to loop in legal".

Both land in the same suggestion inbox, so the rep works one queue either way.

## Related settings

- **Assignment Rules** (**Settings → Assignment Rules**) route new leads to
  reps — round-robin or criteria-based.
- **SLA Policies** (**Settings → SLA Policies**) set response-time targets;
  breaches surface as lead-SLA suggestions and on the record.
