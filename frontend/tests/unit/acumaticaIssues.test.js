import { describe, it, expect } from 'vitest'
import {
  canConfirmNew,
  duplicateCandidates,
  formatIssueTime,
  hasSameVat,
  settingsManagedElsewhere,
} from '../../src/utils/acumaticaIssues.js'

const issue = (candidates, kind = 'Possible Duplicate') => ({
  kind,
  candidates,
})

describe('duplicateCandidates', () => {
  it('offers to link a customer no organization here holds yet', () => {
    expect(
      duplicateCandidates(
        issue([
          {
            customer_id: 'C-A00412',
            organization: null,
            organization_name: 'Zeta Mining',
            reasons: ['same name'],
          },
        ]),
      ),
    ).toEqual([
      {
        customerId: 'C-A00412',
        organization: null,
        name: 'Zeta Mining',
        reasons: ['same name'],
        canLink: true,
      },
    ])
  })

  it('does not offer to link one another organization already holds', () => {
    const [c] = duplicateCandidates(
      issue([
        {
          customer_id: 'C-A00403',
          organization: 'SBS Engineering',
          reasons: ['similar name'],
        },
      ]),
    )
    expect(c.canLink).toBe(false)
    expect(c.name).toBe('SBS Engineering')
  })

  it('skips rows without a code and repeats', () => {
    expect(
      duplicateCandidates(
        issue([
          { customer_id: 'C-1', reasons: [] },
          { customer_id: 'C-1', reasons: [] },
          { organization: 'x' },
          null,
        ]),
      ).map((c) => c.customerId),
    ).toEqual(['C-1'])
  })

  it('is empty for other kinds and for missing or malformed candidates', () => {
    expect(
      duplicateCandidates(issue([{ customer_id: 'C-1' }], 'Push Failed')),
    ).toEqual([])
    expect(duplicateCandidates(issue(undefined))).toEqual([])
    expect(duplicateCandidates(issue('[]'))).toEqual([])
    expect(duplicateCandidates(null)).toEqual([])
  })
})

describe('canConfirmNew', () => {
  it('allows any possible duplicate to be confirmed as new, a VAT match too', () => {
    expect(
      canConfirmNew(issue([{ customer_id: 'C-1', reasons: ['same name'] }])),
    ).toBe(true)
    expect(
      canConfirmNew(
        issue([{ customer_id: 'C-2', reasons: ['same VAT number'] }]),
      ),
    ).toBe(true)
  })

  it('is only for possible duplicates', () => {
    expect(canConfirmNew(issue([], 'Push Blocked'))).toBe(false)
  })
})

describe('hasSameVat', () => {
  it('says when a candidate shares the VAT number', () => {
    expect(
      hasSameVat(
        issue([
          { customer_id: 'C-1', reasons: ['similar name'] },
          { customer_id: 'C-2', reasons: ['same VAT number'] },
        ]),
      ),
    ).toBe(true)
    expect(
      hasSameVat(issue([{ customer_id: 'C-1', reasons: ['same name'] }])),
    ).toBe(false)
    expect(hasSameVat(null)).toBe(false)
  })
})

describe('formatIssueTime', () => {
  it('shows date and minutes, without seconds or microseconds', () => {
    expect(formatIssueTime('2026-11-02 09:28:17.161536')).toBe(
      '2026-11-02 09:28',
    )
    expect(formatIssueTime('2026-11-02T09:28:17')).toBe('2026-11-02 09:28')
  })

  it('leaves nothing as nothing and an unknown shape as it came', () => {
    expect(formatIssueTime(null)).toBe('')
    expect(formatIssueTime('')).toBe('')
    expect(formatIssueTime('yesterday')).toBe('yesterday')
  })
})

describe('settingsManagedElsewhere', () => {
  it('is a refusal, not a failure, on a permission error', () => {
    expect(
      settingsManagedElsewhere({ exc_type: 'PermissionError', messages: [] }),
    ).toBe(true)
    expect(settingsManagedElsewhere({ httpStatus: 403 })).toBe(true)
  })

  it('leaves every other failure, and none, to the error state', () => {
    expect(settingsManagedElsewhere(null)).toBe(false)
    expect(
      settingsManagedElsewhere({ httpStatus: 500, exc_type: 'ValueError' }),
    ).toBe(false)
    expect(settingsManagedElsewhere(new TypeError('Failed to fetch'))).toBe(
      false,
    )
  })
})
