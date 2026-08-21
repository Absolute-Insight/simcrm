# The suggestion inbox

The inbox is the proactive surface: a ranked list of things worth doing, each
one carrying the evidence that put it there. It opens from **Suggestions** in
the sidebar, and the badge is how many are open for you. On a phone it is a
page of its own.

The same list, filtered to one record, appears on a deal or lead under **Needs
attention**.

## The signals

Six rules run once an hour. Three of them look backwards — something has already
gone wrong. Three look forwards, which is the point of the tier: a rule that
only reports elapsed time is a report, not a prediction.

| Signal | Fires when | Looks |
|---|---|---|
| **Idle deal** | No activity of any kind for the idle threshold (7 days by default). | Back |
| **No next step** | An open deal has no open task and no next step recorded. | Back |
| **Lead SLA breached** | A lead's first-response deadline has passed unanswered. | Back |
| **Close date at risk** | The expected close date is inside the horizon while the stage probability says it will not be met. | Forward |
| **Deal cooling** | The deal's own contact cadence is decaying — the gaps between touches are widening — days before the flat idle threshold would trip. | Forward |
| **Stale plan item** | A planned activity is past its date and nothing matched it. | Back |

Activity means a communication, a task, a call log or a human comment. An
assignment comment does not count as activity; nobody talked to the customer.

## Urgency

Each suggestion carries a score, shown as a word rather than a number:
**Urgent** at 70 and above, **Soon** at 40, **Low** below that. The word is what
carries the severity — a hue alone is lost to a colour-blind reader and to a
printed page.

## Accepting and dismissing

**Accept** performs the action the suggestion describes — create a task,
schedule a call, draft a reply, update a field — with the record already filled
in. **Dismiss** asks for a reason.

The reason is not a write-only field. Dismissing the same kind of signal
repeatedly stretches how long that signal stays quiet for you, up to four times
the base cooldown. The queue learns from your dismissals instead of only
recording them. An administrator can read the same rows back in Settings →
Assistant, under *What reps are rejecting* — a threshold reps keep rejecting is
the one worth changing, and guessing at which is exactly what that panel exists
to stop.

## Why the inbox does not grow forever

Left alone, *no next step* would fire on every open deal with no task — on an
imported pipeline that is one suggestion per deal, thousands of them, against a
list that shows fifty. So each rep has a ceiling (**30** by default, in Settings
→ Assistant). The highest-scoring suggestions fill it and the rest are not
created at all. When your inbox is full you get nothing new until you work it
down, which is the correct behaviour for a worklist.

Unactioned suggestions expire after their TTL, 14 days by default. Settled rows
are purged after 90.

## When nothing appears

- The scheduler is not running, so the hourly job never fires.
- **Generate suggestions** is off in Settings → Assistant.
- Your inbox is already at the ceiling.
- There is genuinely nothing to report, which on a small, well-tended pipeline
  is the normal state.
