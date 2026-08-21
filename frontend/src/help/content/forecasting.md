# Forecasting

A forecast is the open pipeline weighted by each deal's stage probability, by
the month it is expected to close in. Nothing is modelled or guessed: it is
arithmetic over values you entered and probabilities your administrator set.

## Turning it on

Forecasting ships **off**, and while it is off the two fields it depends on —
**expected deal value** and **expected close date** — are not mandatory on a
deal. Turn it on in Settings, then make sure those fields are being filled in.
A forecast built from deals where most of them are blank is not a small
forecast; it is a wrong one.

Any forecast surface that is empty for this reason says so, rather than
rendering an empty chart next to tiles showing real money.

## Forward and realised are different numbers

This trips people up, so it is worth stating plainly. A **forward-looking**
figure — pipeline, forecast, weighted value — uses the deal's *expected* value.
A **realised** figure — won revenue, actual — uses the value the deal actually
closed at. They are separate columns and they are meant to differ.

So a month can show a forecast of £74m and an actual of £0 with nothing wrong:
the month has not happened yet.

## Snapshots

Once a week the forecast is written down — one row per month, per scope, per
user, for a window from last month to six months out. That is what makes
forecast *accuracy* measurable at all: without a record of what you predicted,
comparing it to what happened is not possible after the fact.

**Forecast vs actual** in Reports reads those snapshots. Early on it will be
thin, because there is only as much history as the site has been running.

Re-running the snapshot on the same day updates in place rather than
duplicating.
