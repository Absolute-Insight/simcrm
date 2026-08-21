# Automation rules

An automation rule reacts to something happening to a record, without anyone
writing code. **Settings → Automation & Rules → Automation Rules.**

A rule is four decisions:

## 1. What it watches

**Document type** — Lead or Deal — and a **trigger**:

- **Created** — the record has just been made.
- **Status Changed** — its status has just moved. Optionally narrow that to one
  destination with **To Status**, so the rule only fires on the transition you
  care about.

## 2. Whether it applies

**Condition** is an optional Python expression with the record available as
`doc`. It runs sandboxed and has nothing else in scope.

```python
doc.deal_value > 50000
```

Left blank, the rule always applies to its trigger.

## 3. What it does

- **Create Task** — with a priority and an optional **Due In Days**.
- **Create Suggestion** — a row in the rep's inbox with an urgency you set,
  which is how a rule of your own joins the built-in signals rather than
  competing with them.

**Assign to record owner** puts it on whoever owns the record. Off, it is
unassigned.

## 4. What it says

**Title template** and **Description template** accept `{{ doc.field }}`:

```
Contract review for {{ doc.organization }}
```

`doc` is the only thing in scope, on purpose. A template with the framework's
full helper set in scope would let anyone who can author a rule read the
database through a task title.

## Order and isolation

**Priority** decides which rule runs first when several match; lower first.

Each rule runs isolated. One that errors is logged and skipped, and the rest of
the rules on that record still run — a bad rule costs its own action and nothing
else.

## A rule that never fires

Check, in order: is it **Enabled**; does the **document type** match; did the
status actually *change* (a save that leaves the status alone is not a status
change); does **To Status** exactly match the status name; does the
**condition** evaluate true.
