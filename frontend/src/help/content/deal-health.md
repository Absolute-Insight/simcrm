# Deal health

Every open deal carries a health score from 0 to 100, rescored once an hour. It
is shown on the record under **Needs attention**, and the dashboard counts the
low ones into its at-risk tile.

Higher is healthier. The score starts at 100 and each thing wrong with the deal
subtracts from it. Eight things can:

| Factor | Subtracts | Fires when |
|---|---|---|
| **Idle** | up to 50 | No activity for more than three days, 4 points a day after that. |
| **Stage stagnation** | up to 20 | In the same stage for more than three weeks. |
| **Slow stage** | up to 20 | Taking at least 1.5× the median time your team spends in that stage. |
| **Close date passed** | up to 30 | The expected close date is behind you. |
| **Slip risk** | 25 | Due to close inside the horizon, from a stage that historically closes less than 60% of the time. |
| **Cadence slowing** | up to 20 | Contact has slowed to at least twice this deal's own usual gap. |
| **No open task** | 15 | Nothing is scheduled. |
| **One-sided** | 10 | Effectively no inbound replies — you are the only one talking. |

Two of those are worth reading twice. **Slow stage** compares this deal against
your team's own history in that stage, not against a number somebody picked, and
it stays quiet until at least five deals have been through — below that a median
is one person's habit, not a norm. **Slip risk** fires while the close date is
still ahead of you, which is the only point at which you can do anything about
it.

A feature that cannot be measured is never punished. A deal with no expected
close date does not lose points for not having one.

## The bands

| Band | Score | Reading |
|---|---|---|
| **Healthy** | 70–100 | Nothing to do about the deal as a deal. |
| **At risk** | 40–69 | One or more signals are firing. Look at the factors. |
| **Critical** | below 40 | Several are. This is where a manager should be asking. |

As with urgency, the band is a word first. The meter is there to be glanced at,
not to be read precisely.

## The factors

Under the score is the list of what moved it, in plain language — "No activity
for 23 days", "No next step recorded". That list is the whole explanation: there
is no hidden term, and no model involved. Two deals with the same score got
there for reasons you can compare.

## What it is not

It is not a probability of closing. Stage probability is that, and it is set by
your administrator per deal status. Health measures whether the deal is being
*worked*, which is a different question and the one you can do something about
today.
