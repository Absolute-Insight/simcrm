import { describe, it, expect } from 'vitest'
import {
  canConfirmNew,
  duplicateCandidates,
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
  it('allows a name or email match to be confirmed as new', () => {
    expect(
      canConfirmNew(issue([{ customer_id: 'C-1', reasons: ['same name'] }])),
    ).toBe(true)
  })

  it('refuses past a same-VAT match', () => {
    expect(
      canConfirmNew(
        issue([
          { customer_id: 'C-1', reasons: ['similar name'] },
          { customer_id: 'C-2', reasons: ['same VAT number'] },
        ]),
      ),
    ).toBe(false)
  })

  it('is only for possible duplicates', () => {
    expect(canConfirmNew(issue([], 'Push Blocked'))).toBe(false)
  })
})
