---
title: Reports and digests
category: Analytics & reporting
order: 2
---

The **Reports** page holds the built-in reports. Every report row is computed
by the same metrics layer as the dashboard tiles — the number in a report and
the number on a tile are the same number for the same period.

## The built-in reports

| Report | What it answers |
|---|---|
| **Pipeline by stage** | Open deals created in the chosen period, per stage — count, expected value and weighted value |
| **Funnel conversion** | How records move through the funnel in a period |
| **Plan adherence by rep** | Of the activities each rep planned, how many landed |
| **Forecast vs actual** | Forecasted revenue per month against what actually closed |
| **Pipeline by segment** | The open pipeline broken down by segment |
| **Quota attainment by rep** | Closed-won against target, per rep |

## Working with a report

- **Period** — pick the date range the report covers.
- **Export CSV** — download the rows exactly as shown.
- **Print** — a print-friendly view for sharing.
- Manager scoping follows the sales hierarchy: you see the reps you manage.
  Every report is scoped by permission *before* it aggregates — no report
  shows a total you are not allowed to see the rows of.
- **Forecast vs actual** is blank while forecasting is switched off in
  Settings, and says so above the table rather than showing an empty grid.
  An empty report is not a broken one: check the period and territory filter
  first.

## Scheduled digests

**Settings → Report Digests** emails a report on a schedule. Each recipient
gets the report scoped to *their own* visibility — a rep receives their rows,
a manager the team's. Recipients must be active users with a sales role — the
same people the Reports page admits. See **Scheduled digests**.
