---
title: Deals and the pipeline
category: Working with records
order: 2
---

A deal is a qualified opportunity moving through your pipeline toward closed
won or closed lost.

## The fields that drive everything else

A few fields on the deal feed the analytics, forecasts and suggestions, so
they are worth keeping honest:

| Field | What reads it |
|---|---|
| **Status / stage** | Pipeline reports, funnel conversion, stage probability — each status carries a probability set by your administrator, read by the forecast, the *close at risk* signal and deal health's slip-risk factor. Set it to what your pipeline actually converts at. |
| **Expected deal value** and **currency** | Every monetary aggregate. Values are converted through the deal's stored exchange rate, so mixed currencies sum correctly. |
| **Expected closure date** | The forecast, and the *close at risk* signal |
| **Closed date** | Set when a deal is won; actual revenue is bucketed by this date |
| **Lost reason** | The lost-deal-reasons chart |

## Needs attention

Open a deal and the **Needs attention** section shows its health: a score with
the named factors that produced it — days idle, no next step, a slowing
contact cadence, too long in the current stage. See **Deal health** for how
the score works.

## Winning and losing

Mark a deal **Won** and its closed date and value flow into actuals, quota
attainment and forecast accuracy. Mark it **Lost** and you will be asked for a
lost reason; lost deals are excluded from the forecast entirely.

## Tips

- The org page lists every deal at that organization, so three deals at one
  company stay distinguishable.
- Every dashboard tile that counts deals can be clicked to open the list of
  the exact records behind the number.
