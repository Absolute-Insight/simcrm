import { describe, expect, it } from 'vitest'
import { dealLabel } from '@/utils/dealLabel'

describe('dealLabel', () => {
  it('is the organization when there is one', () => {
    expect(dealLabel({ name: 'CRM-DEAL-1', organization: 'Acme' })).toBe('Acme')
  })

  it('falls back to the deal, so a row is never nameless', () => {
    expect(dealLabel({ name: 'CRM-DEAL-1', organization: '' })).toBe(
      'CRM-DEAL-1',
    )
    expect(dealLabel({ name: 'CRM-DEAL-1' })).toBe('CRM-DEAL-1')
  })
})
