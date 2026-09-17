import { describe, expect, it } from 'vitest'
import {
  budgetStatusMessage,
  limitStatusMessage,
  unavailableReasonMessage,
  canRetryUnavailable,
  isBudgetReason,
} from '@/utils/agentStatus'

describe('agent degrade reasons', () => {
  it('knows which reasons mean the day is spent', () => {
    expect(isBudgetReason('budget')).toBe(true)
    expect(isBudgetReason('user_budget')).toBe(true)
    expect(isBudgetReason('rate_limited')).toBe(false)
    expect(isBudgetReason('')).toBe(false)
    expect(isBudgetReason(undefined)).toBe(false)
  })

  it('offers a retry only when waiting a moment can help', () => {
    expect(canRetryUnavailable('')).toBe(true)
    expect(canRetryUnavailable('rate_limited')).toBe(true)
    expect(canRetryUnavailable('budget')).toBe(false)
    expect(canRetryUnavailable('user_budget')).toBe(false)
  })

  it('says the allowance is used up and when it comes back, never "try again"', () => {
    for (const reason of ['budget', 'user_budget']) {
      const copy = budgetStatusMessage(reason)
      expect(copy).toMatch(/allowance/i)
      expect(copy).toMatch(/tomorrow/i)
      expect(copy).not.toMatch(/try again/i)
    }
    expect(budgetStatusMessage('user_budget')).toMatch(/your share/i)
    expect(budgetStatusMessage('rate_limited')).toBe('')
    expect(budgetStatusMessage('')).toBe('')
  })
})

describe('a question the model had no room for (#237)', () => {
  it('names a reply that ran out of tokens instead of calling it an outage', () => {
    expect(limitStatusMessage('reply_length')).toMatch(/ran out of room/i)
    expect(limitStatusMessage('context_length')).toMatch(/more room/i)
    expect(limitStatusMessage('rate_limited')).toBe('')
    expect(limitStatusMessage(undefined)).toBe('')
  })

  it('does not offer Try again: the same question fails the same way', () => {
    expect(canRetryUnavailable('reply_length')).toBe(false)
    expect(canRetryUnavailable('context_length')).toBe(false)
    expect(canRetryUnavailable('rate_limited')).toBe(true)
    expect(canRetryUnavailable(undefined)).toBe(true)
  })

  it('gives one sentence for whichever named reason applies', () => {
    expect(unavailableReasonMessage('budget')).toBe(
      budgetStatusMessage('budget'),
    )
    expect(unavailableReasonMessage('reply_length')).toBe(
      limitStatusMessage('reply_length'),
    )
    expect(unavailableReasonMessage('')).toBe('')
  })
})
