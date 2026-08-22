---
title: Assignment, SLAs and hierarchy
category: Getting started
order: 4
---

Three separate settings that between them decide who owns a record, how fast it
must be answered, and who can see whose numbers.

## Assignment rules

**Settings → Assignment Rules.** Decide who a new lead or deal lands on — round
robin, load balanced, or by rule. Without one, new records arrive owned by
whoever created them, which for anything arriving through a web form or the
API means nobody is looking at it.

## SLA policies

**Settings → SLA Policies.** An SLA sets a first-response deadline for a lead,
within defined working hours and per priority.

This is what the **lead SLA** signal reads. With no policy in place there is no
deadline, so that signal can never fire — which is a legitimate configuration,
just not an accidental one.

## Sales hierarchy

**Settings → Sales Hierarchy.** Who reports to whom.

It decides more than an org chart:

- which reps appear in a manager's dashboard filter,
- whose rows a manager sees in **Plan adherence by rep** and **Quota attainment
  by rep**,
- whose plans a manager can read in the Planner.

A manager with nobody under them sees only their own numbers, everywhere, and
nothing tells them the hierarchy is the reason. Set it up before wondering why a
team view is empty.
