import { describe, it, expect } from 'vitest'
import {
  lostReasonError,
  bulkUpdateOutcome,
} from '../../src/utils/lostReason.js'

describe('lostReasonError', () => {
  it('requires a reason', () => {
    expect(lostReasonError('', '')).toBe('Lost Reason is required')
    expect(lostReasonError(null, 'notes')).toBe('Lost Reason is required')
  })

  it('requires notes only when the reason is Other', () => {
    expect(lostReasonError('Other', '')).toMatch(/Lost Notes are required/)
    expect(lostReasonError('Other', 'went elsewhere')).toBe('')
    expect(lostReasonError('Price', '')).toBe('')
  })
})

describe('bulkUpdateOutcome', () => {
  it('reports the docnames that failed to save', () => {
    expect(bulkUpdateOutcome(['CRM-DEAL-1', 'CRM-DEAL-2'])).toEqual({
      status: 'failed',
      failed: ['CRM-DEAL-1', 'CRM-DEAL-2'],
    })
  })

  it('treats an empty list as every record saved', () => {
    expect(bulkUpdateOutcome([])).toEqual({ status: 'done', failed: [] })
  })

  it('treats no list as an enqueued job (20 records or more)', () => {
    expect(bulkUpdateOutcome(null).status).toBe('enqueued')
    expect(bulkUpdateOutcome(undefined).status).toBe('enqueued')
  })
})
