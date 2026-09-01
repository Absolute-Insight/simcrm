---
title: The Analyst
category: AI & automation
order: 4
---

The Analyst is a page in the sidebar for administrators. You ask a question
about the business in plain language — "How did revenue grow over the last six
months?", "Which reps are behind quota this quarter?", "Which deals and
accounts are likely to go quiet?", "Project revenue for the next quarter" —
and it answers with Vectora's own figures and a short narrative over them.

It reads nothing at all until an administrator switches on **Allow the analyst
to read CRM and ERP data** in **Settings → Assistant**. Until then the page
shows that the grant is off and links to the setting.

## What it does for you

- **Turns a question into the right calculation.** Vectora has a fixed
  catalogue of calculations — the same ones behind the dashboard and reports —
  and the Analyst chooses from it: revenue from won deals by month, the
  weighted forecast, pipeline by stage, funnel conversion, quota attainment by
  rep, deals at risk, growth rates, lead sources, deals by industry, territory
  and rep, plan adherence, average deal value, time to close, a revenue
  projection from the trend, and accounts going quiet.
- **Runs the calculation and shows you the tables.** The rows on screen are
  computed by Vectora, exactly as a report would compute them, for the period
  the question implies (the last twelve months when it does not say).
- **Writes the narrative.** The model reads the finished tables and describes
  what they show, with a few highlights and caveats. Every number on screen
  comes from the calculation, never from the model; if the words and the table
  disagree, the table is right.
- **Reads the ERP when one is connected.** With Acumatica or ERPNext enabled,
  it can also report invoices issued, payments received, open receivables and
  net cashflow by month, taken from the ERP and labelled with the ERP's name.
  If the ERP cannot be reached, the CRM figures still appear and the answer
  says the ERP source was unavailable.

## When it runs

Only when an administrator asks it a question, and only after the grant above
is on. Nothing runs on a schedule and nothing is stored: the conversation
lives in the browser tab for the session. Each question counts against the
site's daily call budget.

The calculations it runs are scoped to the person asking, the same way the
dashboard is — the Analyst cannot show a figure its user could not see in a
report.

## What it never does

- **It never writes SQL, and never runs a query it composed.** It picks from
  the catalogue; Vectora's own code runs the calculation. There is no way to
  ask it for an arbitrary query.
- **It never changes data.** It cannot create, edit or delete records, alter
  a target or a forecast, or change a setting.
- **It never invents a number.** The figures come from the calculation. A
  question the figures cannot answer gets "the data does not cover that", not
  an estimate.
- **It never runs for a non-administrator**, and never at all while the grant
  in Settings → Assistant is off.

## Honest definitions

Two words the Analyst uses mean less than they might in another tool, and it
is better to know that before reading an answer.

- **Cashflow.** From Vectora alone, "cashflow" means realised revenue from won
  deals plus the weighted forecast — money the pipeline says is coming, not
  money in the bank. Real cash figures (invoices issued, payments received,
  open receivables, net cashflow) come only from the ERP, and only when one is
  connected; they are labelled with the ERP's name so you can tell the two
  apart.
- **Maintenance.** "Maintenance" means accounts and deals predicted to go
  quiet — from the same contact-cadence and slip-risk signals that feed the
  suggestions inbox and deal health. Equipment maintenance prediction is not
  available: the CRM holds no installed base and no service history, so there
  is nothing to predict it from.

## Reading an answer

Treat the narrative the way you would a colleague's first read of a report:
useful, quick, and worth checking against the table underneath it. Each table
can be exported as CSV, so a figure you want to act on can go straight into
the meeting.
