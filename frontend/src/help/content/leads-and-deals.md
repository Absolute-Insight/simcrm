# Leads, deals and records

Vectora keeps the record model of Frappe CRM, which most of this page describes
briefly — the parts worth your time are elsewhere in this help centre.

| Record | What it holds |
|---|---|
| **Lead** | Somebody who might become a customer. Has a status, an owner and, if a policy applies, a first-response clock. |
| **Deal** | An opportunity with a value, a stage, an expected close date and an owner. |
| **Organization** | The company. Deals and contacts hang off it. |
| **Contact** | A person. Can belong to an organization. |
| **Task** | Something to do, on a record or standalone. An *open* task is what several signals look for. |
| **Note** | Free text on a record. |
| **Call log** | An inbound or outbound call, logged by the telephony integration or by hand. |

## Lead to deal

A qualified lead is converted from the lead itself. The conversion carries the
organization and contact across, so the deal starts with its counterparty
already attached rather than needing to be re-keyed.

## Stage probability, and why it matters more than it looks

Each deal status carries a probability, set by your administrator in Settings.
It is not decoration. It is read by:

- **Forecasting**, which weights every open deal by it,
- the **close date at risk** signal, which fires when a deal is due to close
  soon from a stage that rarely does,
- **deal health**, through the same slip-risk factor.

Set those probabilities to what your pipeline actually converts at, and three
features get more accurate at once. Leave them at their defaults and all three
are guessing with your data.

## Views, filters and imports

Saved views, public views and pinned views work as they do in Frappe CRM.
Data import is under its own route from the list views, and takes CSV.
