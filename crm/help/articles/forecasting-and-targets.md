---
title: Forecasting and sales targets
category: Analytics & reporting
order: 3
---

## The forecast

The forecasted-revenue chart projects each month from open deals' expected
value, expected close date and stage probability, and lays actual closed
revenue alongside.

The rules that keep it honest:

- **Lost deals are excluded entirely.** A lost deal forecasts nothing.
- **Actuals are bucketed by the month a deal really closed**, not the month it
  was expected to close.
- **A settled month with nothing closed shows 0, not blank** — "zero revenue"
  and "no data yet" stay distinguishable; only future months are blank.
- Forecasting is switched on per site; when it is off, the charts say so
  instead of drawing an empty line. While it is off, **expected deal value**
  and **expected close date** are not mandatory on a deal — once it is on,
  make sure they are being filled in.
- Forward-looking figures (pipeline, forecast) use *expected* value; realised
  figures (won revenue, actual) use what the deal closed at. A future month
  with a large forecast and an actual of 0 has nothing wrong with it.

## Forecast accuracy

Vectora snapshots the forecast weekly. The accuracy chart compares the last
snapshot taken *before* each month began against that month's live actual —
your forecast is measured against reality, not against what it later became.
Snapshots cover last month to six months out; re-running on the same day
updates in place.
The chart starts drawing once enough snapshot history has accumulated.

## Sales targets (quotas)

- Managers set **monthly targets per rep** in **Settings → Sales Targets** — a
  rep × month grid with a fill-year shortcut. Reps see their own row
  read-only.
- Targets are in the base currency. Deal values in other currencies are
  converted through each deal's stored exchange rate.
- Quarter, year and team numbers are always sums of the monthly rows — a team
  target can never disagree with the reps' targets underneath it.
- **Quota attainment** (dashboard tile and report) measures closed-won revenue
  against the target, pro-rated by the days the selected period covers.
