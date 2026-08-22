---
title: Integrations
category: Getting started
order: 5
---

Vectora connects to a handful of outside systems. Each is opt-in and each ships
disabled.

## Telephony — Twilio and Exotel

**Settings → Telephony.** Once connected, calls can be placed from a record and
inbound calls raise a screen pop with the matching contact. Calls are logged
against the record, which matters beyond the log itself: a call counts as
activity, so it keeps the idle and cooling signals honest.

Credentials come from your Twilio or Exotel account; their own documentation is
the right source for where to find them.

## WhatsApp

**Settings → WhatsApp.** Sends and receives through the WhatsApp Business API,
threaded onto the record.

## ERPNext

**Settings → ERPNext.** Links a CRM deal to an ERPNext customer and quotation,
so a won deal does not have to be re-keyed into the accounting system. It needs
an ERPNext site and an API key with permission to create the records you map
to.

## Lead syncing

**Settings → Lead Syncing** brings leads in from outside sources on a schedule.

The Facebook lead-ads connector ships **disabled and hidden**, and that is not
an oversight. It requests one page of results and ignores the paging cursor,
then marks everything up to now as synced — so a form that produces more leads
than fit in one page loses the remainder silently. The failure only shows up
when a campaign does well, which is the worst time to find it. Leads still
arrive through the web form, the API and manual entry.

## Exchange rates

Multi-currency deals are converted using rates fetched from a public exchange
rate service; each deal stores the rate it was converted at.

## Web forms

A web form captures leads straight into the CRM from your site, with the fields
you choose and an assignment rule deciding who picks them up.
