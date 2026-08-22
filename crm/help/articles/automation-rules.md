---
title: Automation rules
category: Proactive selling
order: 4
---

Automation rules are deterministic if-this-then-that rules an admin defines in
**Settings → Automation Rules**. They run on record changes and never depend
on the model tier — a rule fires the same way every time, model on or off.

## What a rule is

- **A trigger** — the record event the rule watches: **Created**, or
  **Status Changed**, optionally narrowed to one **To Status**.
- **A condition** — an optional sandboxed Python expression with the record as
  `doc` (`doc.deal_value > 50000`). Blank means always.
- **An action** — create a task (with priority and due-in days), or raise a
  suggestion in the owner's inbox with an urgency you set. Title and
  description templates accept `{{ doc.field }}`; `doc` is the only thing in
  scope, on purpose.
- **Priority** decides order when several rules match; lower first. Each rule
  runs isolated, so one that errors is logged and skipped and the rest still
  run.

A rule that never fires: check it is **Enabled**, the document type matches,
the status actually *changed*, **To Status** matches the status name exactly,
and the condition evaluates true.

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
