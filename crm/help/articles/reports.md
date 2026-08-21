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
| **Pipeline by stage** | What is open right now, per stage — a snapshot, so it has no date picker |
| **Funnel conversion** | How records move through the funnel in a period |
| **Plan adherence by rep** | Of the activities each rep planned, how many landed |
| **Forecast vs actual** | Forecasted revenue per month against what actually closed |
| **Pipeline by segment** | The open pipeline broken down by segment |
| **Quota attainment by rep** | Closed-won against target, per rep |

## Working with a report

- **Period** — most reports take a date range; snapshot reports hide the
  picker because the range would change nothing.
- **Export CSV** — download the rows exactly as shown.
- **Print** — a print-friendly view for sharing.
- Manager scoping follows the sales hierarchy: you see the reps you manage.

## Scheduled digests

**Settings → Report Digests** emails a report on a schedule. Each recipient
gets the report scoped to *their own* visibility — a rep receives their rows,
a manager the team's. Recipients must be active users with a CRM role.
