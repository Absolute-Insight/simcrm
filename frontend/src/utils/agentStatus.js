/**
 * The reasons the agent endpoints attach to an `unavailable` status, and the
 * copy each deserves.
 *
 * `unavailable` used to be one word for three situations: the burst limiter
 * (clears within a minute), a model that could not be reached (may be back in
 * a moment) and a spent daily budget (comes back tomorrow). Every surface said
 * "try again in a moment" and offered a Try again button that, for a spent
 * budget, was refunded and never succeeded -- an idle endpoint reported as an
 * outage. The server now names the reason; this is the one place the mapping
 * lives so the surfaces agree.
 */

/** `reason` values that mean the day is spent and a retry cannot help. */
export const BUDGET_REASONS = ['budget', 'user_budget']

export function isBudgetReason(reason) {
  return BUDGET_REASONS.includes(reason)
}

/** Whether a Try again action is honest for this `unavailable` reason. */
export function canRetryUnavailable(reason) {
  return !isBudgetReason(reason)
}

/**
 * The sentence for a spent budget, or '' for any other reason so the caller
 * keeps its own "could not be reached" wording.
 */
export function budgetStatusMessage(reason) {
  if (reason === 'user_budget') {
    return __(
      "You have used your share of today's model allowance. It resets tomorrow.",
    )
  }
  if (reason === 'budget') {
    return __(
      "Today's model allowance for this site has been used up. It resets tomorrow.",
    )
  }
  return ''
}
