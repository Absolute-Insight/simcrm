---
title: The weekly planner
category: Proactive selling
order: 3
---

The **Planner** page is your week as concrete activities: calls, emails,
meetings and tasks, one column per day, Monday-based. Plans resolve against
what actually happened — plan-vs-actual is computed, never self-reported.

## Building a week

- **Add items by hand**: pick an activity type, a day, an optional note and an
  optional deal or lead the item is about.
- **Propose my week** drafts a week from your ten highest-scoring open
  suggestions, spread over the remaining weekdays — a *schedule call*
  suggestion becomes a call, the rest become tasks. It writes nothing until
  you review and save.
- Reschedule or remove items any time; the header rolls up planned / done /
  missed for the week.

## How items get marked Done

A daily matcher links each planned item to real logged activity:

| Planned activity | Fulfilled by |
|---|---|
| Task | A task marked Done |
| Call | A completed call log where you were the caller or receiver |
| Email | A sent email |
| Meeting | A calendar event that was not cancelled |

Matching prefers activity on the same deal or lead the item referenced, then
the closest date, oldest week first. One real activity can only ever fulfil
one planned item.

The verdict is re-derived every run: if the call log behind a Done item is
deleted, the Done goes away again. Items past the matching horizon are settled
as Missed and the week becomes read-only. A missed item is itself a signal: it
comes back to you in the suggestions inbox as a *stale plan*.

## Correcting the matcher

If the matcher gets an item wrong, mark it fulfilled or missed yourself — a
manual override sticks, and the daily job leaves overridden rows alone.

## Managers

Managers can open the plans of the reps they manage (following the sales
hierarchy) but never edit someone else's week. Team-wide **plan adherence** —
settled items that landed — is on the dashboard and in reports.
