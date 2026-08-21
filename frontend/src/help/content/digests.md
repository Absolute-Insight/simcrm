# Scheduled digests

A digest emails a report to a list of people on a schedule, so the weekly
pipeline review does not depend on somebody remembering to export it.

**Settings → Report Digests.**

## What you set

| | |
|---|---|
| **Report** | Any of the six built-in reports. |
| **Frequency** | Daily, or Weekly. |
| **Recipients** | Who receives it. |
| **Enabled** | Off is a valid state — keep a digest configured without sending it. |

Weekly digests go out on Monday. Both frequencies are sent by the daily
scheduler job, so nothing sends at all on a stack whose scheduler is not
running.

## What arrives

The report as a table, rendered for email, with the same numbers the report page
would show — same metrics layer, so a digest and the screen cannot disagree.

One failing digest does not stop the others. Each is isolated, the same way an
automation rule is, so a report that errors costs its own email and nothing
else.
