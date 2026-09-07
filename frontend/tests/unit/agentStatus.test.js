import { describe, expect, it } from 'vitest'
import {
  budgetStatusMessage,
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
