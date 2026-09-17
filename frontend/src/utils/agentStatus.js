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
  // the same question runs out of room the same way; only a different one helps
  return !isBudgetReason(reason) && !LIMIT_REASONS.includes(reason)
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

/** `reason` values where the model was reached but the question did not fit it. */
export const LIMIT_REASONS = ['reply_length', 'context_length']

/**
 * The sentence for a question the model had no room for, or '' otherwise.
 *
 * Neither is weather. `reply_length`: a reasoning model spent its whole reply
 * budget thinking and wrote no answer. `context_length`: the prompt was longer
 * than the window the endpoint serves. Asking the same thing again fails the
 * same way, so the honest advice is to ask differently, not to wait.
 */
export function limitStatusMessage(reason) {
  if (reason === 'reply_length') {
    return __(
      'The model ran out of room before it could answer. Ask something shorter or more specific.',
    )
  }
  if (reason === 'context_length') {
    return __(
      'This question needs more room than the model is set up for. Clear the conversation or ask something narrower.',
    )
  }
  return ''
}

/** Whichever named sentence applies to this `unavailable` reason, or ''. */
export function unavailableReasonMessage(reason) {
  return budgetStatusMessage(reason) || limitStatusMessage(reason)
}
