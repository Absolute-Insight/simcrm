---
title: What Vectora does for you automatically
category: AI & automation
order: 1
---

Most of what Vectora does on its own is a rule: a fixed calculation that runs
on a schedule, reads your records and produces the same result every time. A
few capabilities use a language model — the *words* you read are written by
it, an administrator has to switch it on, and it is off by default. This page
lists both kinds side by side, so you always know which one you are looking at.

| Capability | Kind | What it does | Where you see it |
|---|---|---|---|
| **Signals and the suggestions inbox** | Automatic rule | Checks open deals and leads for idle deals, missing next steps, response targets missed, close dates at risk, a cooling contact cadence and stale plan items, and raises a suggestion for the owner | The **Suggestions** badge in the sidebar; **Needs your attention** on the dashboard |
| **Deal health** | Automatic rule | Scores every open deal from 100 down, subtracting a named amount for each risk factor present | **Needs attention** on the deal page; **Critical deals** on the dashboard |
| **Propose my week** | Automatic rule | Drafts a week's activities from your highest-scoring open suggestions; saves nothing until you do | The **Planner** |
| **Plan vs actual** | Automatic rule | Matches each planned item against the calls, emails, meetings and tasks actually logged, and marks it done or missed | The Planner's planned / done / missed rollup; **Plan adherence** on the dashboard and in reports |
| **Forecast snapshots and accuracy** | Automatic rule | Records the forecast so each month can later be measured against what really closed | The **Forecast accuracy** chart |
| **Quota attainment** | Automatic rule | Closed-won revenue against each rep's monthly target, pro-rated to the period you choose | Dashboard tile and panel; the **Quota attainment by rep** report |
| **Scheduled report digests** | Automatic rule | Emails a report to a list of people, each copy scoped to what that person may see | Your email inbox; **Settings → Report Digests** |
| **Automation rules** | Automatic rule | Your own if-this-then-that rules: when a record is created or changes status, create a task or raise a suggestion | **Settings → Automation Rules**; the suggestions inbox |
| **Assignment rules and SLAs** | Automatic rule | Route a new lead or deal to a rep, and set its first-response deadline | **Settings → Assignment Rules** and **Settings → SLA Policies**; the record page |
| **Website enrichment** | Automatic rule | Reads an organisation's public website and proposes values for empty fields, shown to you for review before anything is written | **Enrich from website** on an organisation |
| **ERP sync** | Automatic rule | Keeps customer, contact and product records in step with your ERP (Acumatica or ERPNext) | Organisation, contact and product records; the ERP page under **Settings** |
| **Currency rates** | Automatic rule | Converts deals in other currencies to the base currency at a fetched rate; each deal keeps the rate it was converted at | Every monetary figure on the dashboard and in reports |
| **Thread summaries** | Uses a model | Condenses a record's email thread into a summary, suggested next steps and a sentiment | **Summarise thread** on a lead or deal |
| **Reply drafts** | Uses a model | Proposes a reply to the latest inbound message and opens it in the compose window for you to edit | **Draft reply** on a lead or deal |
| **The Mentor** | Uses a model | Answers "how does Vectora work?" from these help articles, and cites the ones it used | The box above the search field in this help center |
| **The Assistant** | Uses a model | Answers questions about your company's products, materials, standards and industries from a knowledge base your administrator curates | The sparkle **Assistant** entry in the sidebar |
| **The Analyst** | Uses a model | Turns a plain-language question about the business into one of Vectora's own calculations, then writes a narrative over the figures | The **Analyst** page in the sidebar, administrators only |

## What it does for you

The rules keep watch so you do not have to. They notice a deal going quiet
before it is obviously stuck, keep your plan honest against what you actually
did, measure your forecast against reality, and move records between systems
without re-keying. Each one explains itself — a health score always shows its
factors, a suggestion always shows its reason.

The model-backed capabilities save you reading and typing. They condense a
long thread, draft a first reply, and answer questions in plain language: the
Mentor about Vectora, the Assistant about your own products, the Analyst about
your numbers.

## When it runs

- **Every hour** — the signals run and deal health is rescored.
- **Every day** — plans are matched against actuals, old suggestions are
  purged, due digests are emailed, and the nightly ERP sweep runs. ERP
  webhooks also push changes across as they happen; the nightly sweep is what
  guarantees nothing is missed.
- **Every week** — a forecast snapshot is taken.
- **On the event itself** — automation rules, assignment rules and SLA clocks
  fire the moment a record is created or changes.
- **Only when you ask** — Propose my week, website enrichment, summaries,
  drafts, the Mentor, the Assistant and the Analyst. None of these run in the
  background.

All the scheduled work needs the scheduler running. On a self-hosted stack
where it is not, the proactive half of the product is silent — and that
silence looks exactly like nothing being wrong.

## What it never does

- **Nothing writes to a record without a person.** Suggestions, proposed
  weeks, enrichment values and reply drafts are all shown to you first. You
  accept, save, confirm or send; until then they are proposals. Automation
  rules create only a task or a suggestion, which you then act on.
- **No rule depends on the model.** Signals, health, planning, forecasting,
  quotas, digests, sync and rates all work with the model switched off, and
  nothing a model writes can change any of their results.
- **No model runs unasked.** Every model call is a button you press or a
  question you type, it is rate-limited per person and capped per day, and it
  goes only to the endpoint your administrator configured.
- **No model reads what you cannot.** Each surface reads a fixed source — the
  manual, the knowledge base, or calculations already scoped to your own
  permissions — and nothing beyond it.

## How to read a model's answer

Anything a model writes is a proposal to check, not a fact. A summary or a
draft is generated from an email thread, and a thread contains whatever the
other party chose to write — so read before you trust, and always before you
send.

In the Analyst the figures on screen are Vectora's own calculations, produced
by the same code as the dashboard and reports; only the words around them are
the model's. If the narrative and the table disagree, the table is right.

Nothing a model writes is ever sent, saved or acted on without a person doing
it. The one place a model's text can go is in front of you.
