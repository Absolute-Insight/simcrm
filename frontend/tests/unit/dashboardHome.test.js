import { describe, expect, it } from 'vitest'
import {
  adherencePercent,
  applyPanelPreference,
  deltaTone,
  drilldownFor,
  groupRisksByRecord,
  mondayOf,
  movePanel,
  reorderVisiblePanel,
  planBreakdown,
  riskReason,
  standardViewPayload,
  toISODate,
} from '@/utils/dashboardHome'

describe('toISODate', () => {
  it('formats a Date in local time, not UTC', () => {
    // 23:30 local on the 5th is the 6th in UTC east of Greenwich; a dashboard
    // that shifts a day at teatime is worse than no dashboard.
    expect(toISODate(new Date(2026, 7, 5, 23, 30))).toBe('2026-08-05')
  })

  it('accepts an ISO string and trims a time component', () => {
    expect(toISODate('2026-08-05 09:00:00')).toBe('2026-08-05')
  })

  it('returns an empty string for junk', () => {
    expect(toISODate(null)).toBe('')
    expect(toISODate('not a date')).toBe('')
  })
})

describe('mondayOf', () => {
  it('returns the same day for a Monday', () => {
    expect(mondayOf('2026-08-10')).toBe('2026-08-10')
  })

  it('walks back to Monday from mid-week', () => {
    expect(mondayOf('2026-08-14')).toBe('2026-08-10')
  })

  it('treats Sunday as the end of its week, not the start', () => {
    expect(mondayOf('2026-08-16')).toBe('2026-08-10')
  })

  it('crosses a month boundary', () => {
    expect(mondayOf('2026-08-02')).toBe('2026-07-27')
  })

  it('returns an empty string for junk', () => {
    expect(mondayOf(undefined)).toBe('')
  })
})

describe('planBreakdown', () => {
  const items = [
    { planned_date: '2026-08-14', status: 'Done' },
    { planned_date: '2026-08-14', status: 'Planned' },
    { planned_date: '2026-08-14', status: 'Missed' },
    { planned_date: '2026-08-15', status: 'Planned' },
  ]

  it('counts the whole week when no day is given', () => {
    const out = planBreakdown(items)
    expect(out).toMatchObject({ planned: 4, done: 1, missed: 1, open: 2 })
  })

  it('narrows to one day', () => {
    const out = planBreakdown(items, { on: '2026-08-14' })
    expect(out).toMatchObject({ planned: 3, done: 1, missed: 1, open: 1 })
    expect(out.items).toHaveLength(3)
  })

  it('matches a datetime planned_date against a date', () => {
    const out = planBreakdown(
      [{ planned_date: '2026-08-14 00:00:00', status: 'Done' }],
      { on: '2026-08-14' },
    )
    expect(out.planned).toBe(1)
  })

  it('survives an absent list', () => {
    expect(planBreakdown(null)).toMatchObject({ planned: 0, open: 0 })
  })
})

describe('adherencePercent', () => {
  it('rounds to a whole percent', () => {
    expect(adherencePercent({ planned: 3, done: 2 })).toBe(67)
  })

  it('is zero rather than NaN with nothing planned', () => {
    expect(adherencePercent({ planned: 0, done: 0 })).toBe(0)
    expect(adherencePercent()).toBe(0)
  })
})

describe('groupRisksByRecord', () => {
  const suggestions = [
    {
      signal: 'idle_deal',
      reference_doctype: 'CRM Deal',
      reference_docname: 'DEAL-1',
      user: 'rep@example.com',
      score: 40,
      factors: '[{"key":"idle_days","label":"No activity for 12 days"}]',
    },
    {
      signal: 'no_next_step',
      reference_doctype: 'CRM Deal',
      reference_docname: 'DEAL-1',
      score: 80,
      factors: '[{"key":"has_open_task","label":"No open task"}]',
    },
    {
      signal: 'close_at_risk',
      reference_doctype: 'CRM Deal',
      reference_docname: 'DEAL-2',
      score: 60,
      factors: '[{"key":"days_to_close","label":"Expected close in 2 days"}]',
    },
    {
      signal: 'lead_sla',
      reference_doctype: 'CRM Lead',
      reference_docname: 'LEAD-1',
      score: 99,
      factors: '[]',
    },
  ]

  it('collapses two signals on one deal into one row with both reasons', () => {
    const rows = groupRisksByRecord(suggestions)
    const deal1 = rows.find((r) => r.docname === 'DEAL-1')
    expect(deal1.signals).toEqual(['idle_deal', 'no_next_step'])
    expect(deal1.factors.map((f) => f.label)).toEqual([
      'No activity for 12 days',
      'No open task',
    ])
  })

  it('scores a record by its worst contributing suggestion', () => {
    const rows = groupRisksByRecord(suggestions)
    expect(rows[0]).toMatchObject({ docname: 'DEAL-1', score: 80 })
  })

  it('keeps the owner from the first suggestion that names one', () => {
    const rows = groupRisksByRecord(suggestions)
    expect(rows.find((r) => r.docname === 'DEAL-1').user).toBe(
      'rep@example.com',
    )
  })

  it('drops signals that are not about deal risk', () => {
    const rows = groupRisksByRecord(suggestions)
    expect(rows.some((r) => r.docname === 'LEAD-1')).toBe(false)
  })

  it('sorts worst first and honours a limit', () => {
    const rows = groupRisksByRecord(suggestions, { limit: 1 })
    expect(rows).toHaveLength(1)
    expect(rows[0].docname).toBe('DEAL-1')
  })

  it('de-duplicates identical factor labels across signals', () => {
    const rows = groupRisksByRecord([
      {
        signal: 'idle_deal',
        reference_doctype: 'CRM Deal',
        reference_docname: 'DEAL-9',
        score: 1,
        factors: '[{"key":"a","label":"Same reason"}]',
      },
      {
        signal: 'deal_cooling',
        reference_doctype: 'CRM Deal',
        reference_docname: 'DEAL-9',
        score: 2,
        factors: '[{"key":"b","label":"Same reason"}]',
      },
    ])
    expect(rows[0].factors).toHaveLength(1)
  })

  it('carries the rationale so a row can explain itself without factors', () => {
    const rows = groupRisksByRecord([
      {
        signal: 'idle_deal',
        reference_doctype: 'CRM Deal',
        reference_docname: 'DEAL-7',
        score: 5,
        factors: '{"idle_days": 30}',
        rationale: 'No activity on this deal for 30 days.',
      },
    ])
    expect(rows[0].factors).toEqual([])
    expect(rows[0].rationales).toEqual([
      'No activity on this deal for 30 days.',
    ])
  })

  it('ignores rows with no reference and an absent list', () => {
    expect(groupRisksByRecord(null)).toEqual([])
    expect(
      groupRisksByRecord([
        { signal: 'idle_deal', reference_doctype: 'CRM Deal' },
      ]),
    ).toEqual([])
  })
})

describe('riskReason', () => {
  it('prefers the factor labels, which are the scannable form', () => {
    expect(
      riskReason({
        factors: [
          { label: 'No open task' },
          { label: 'No next step recorded' },
        ],
        rationales: ['This deal has no open task and no next step recorded.'],
      }),
    ).toBe('No open task · No next step recorded')
  })

  it('falls back to the rationale when the factors did not parse', () => {
    // The legacy `{key: value}` shape is dropped by parseFactors rather than
    // printed raw, which used to leave the panel promising a reason and showing
    // a blank line -- three quarters of the rows on a real rep's inbox.
    expect(
      riskReason({
        factors: [],
        rationales: ['No activity on this deal for 30 days.'],
      }),
    ).toBe('No activity on this deal for 30 days.')
  })

  it('says nothing rather than throwing when a row carries neither', () => {
    expect(riskReason({})).toBe('')
    expect(riskReason(null)).toBe('')
  })
})

describe('standardViewPayload', () => {
  it('carries the existing columns, rows and order through', () => {
    const payload = standardViewPayload(
      {
        label: 'List',
        columns: '[{"key":"organization"}]',
        rows: '["name","organization"]',
        order_by: 'creation desc',
        is_default: 1,
      },
      { doctype: 'CRM Deal', filters: { status: 'Won' } },
    )
    expect(payload).toMatchObject({
      doctype: 'CRM Deal',
      type: 'list',
      label: 'List',
      columns: '[{"key":"organization"}]',
      rows: '["name","organization"]',
      order_by: 'creation desc',
      is_default: true,
      filters: { status: 'Won' },
    })
  })

  it('supplies the defaults the server expects when no view exists yet', () => {
    const payload = standardViewPayload(null, { doctype: 'CRM Lead' })
    expect(payload).toMatchObject({
      label: 'List',
      order_by: 'modified desc',
      group_by_field: 'owner',
      column_field: 'status',
      columns: '[]',
      rows: '[]',
      filters: {},
      is_default: false,
    })
  })

  it('labels a non-list view type', () => {
    expect(
      standardViewPayload(null, { doctype: 'CRM Deal', type: 'kanban' }).label,
    ).toBe('Kanban')
  })
})

describe('drilldownFor', () => {
  const context = {
    openStatuses: ['Qualification', 'Negotiation'],
    wonStatuses: ['Won'],
    fromDate: '2026-07-01',
    toDate: '2026-07-31',
  }

  it('sends open-deal tiles to the deals list filtered to open statuses', () => {
    expect(drilldownFor('ongoing_deals', context)).toEqual({
      doctype: 'CRM Deal',
      routeName: 'Deals',
      filters: { status: ['in', ['Qualification', 'Negotiation']] },
    })
  })

  it('scopes to a rep when the dashboard is filtered to one', () => {
    const out = drilldownFor('ongoing_deals', { ...context, user: 'a@b.c' })
    expect(out.filters.deal_owner).toBe('a@b.c')
  })

  it('bounds won-deal tiles by the dashboard period', () => {
    expect(drilldownFor('won_deals', context).filters).toEqual({
      status: ['in', ['Won']],
      closed_date: ['between', ['2026-07-01', '2026-07-31']],
    })
  })

  it('filters leads to the unconverted ones the tile counted', () => {
    expect(drilldownFor('total_leads', context).filters).toMatchObject({
      converted: 0,
      creation: ['between', ['2026-07-01', '2026-07-31']],
    })
  })

  it('sends plan adherence to the planner rather than a list', () => {
    expect(drilldownFor('plan_adherence', { user: 'a@b.c' })).toEqual({
      routeName: 'Planner',
      query: { user: 'a@b.c' },
    })
  })

  it('refuses to drill a status-based tile with no statuses loaded yet', () => {
    expect(drilldownFor('won_deals', {})).toBeNull()
  })

  it('returns null for a tile with no list behind it', () => {
    expect(drilldownFor('average_deal_value', context)).toBeNull()
    expect(drilldownFor('sales_trend', context)).toBeNull()
  })
})

describe('deltaTone', () => {
  it('reads a rise as good by default and as bad when negative is better', () => {
    expect(deltaTone(5)).toBe('positive')
    expect(deltaTone(5, true)).toBe('negative')
  })

  it('reads a fall the other way round', () => {
    expect(deltaTone(-5)).toBe('negative')
    expect(deltaTone(-5, true)).toBe('positive')
  })

  it('is neutral at zero, including a missing delta', () => {
    expect(deltaTone(0)).toBe('neutral')
    expect(deltaTone(undefined)).toBe('neutral')
  })
})

describe('applyPanelPreference', () => {
  const panels = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]

  it('returns the catalogue untouched with no preference', () => {
    expect(applyPanelPreference(panels, null).map((p) => p.id)).toEqual([
      'a',
      'b',
      'c',
    ])
  })

  it('hides what the user hid', () => {
    expect(
      applyPanelPreference(panels, { hidden: ['b'] }).map((p) => p.id),
    ).toEqual(['a', 'c'])
  })

  it('reorders to the saved order', () => {
    expect(
      applyPanelPreference(panels, { order: ['c', 'a', 'b'] }).map((p) => p.id),
    ).toEqual(['c', 'a', 'b'])
  })

  it('appends a panel the saved order has never heard of', () => {
    // A release that adds a panel must not make it invisible to every user who
    // has ever touched the customise menu.
    expect(
      applyPanelPreference([...panels, { id: 'new' }], {
        order: ['c', 'b', 'a'],
      }).map((p) => p.id),
    ).toEqual(['c', 'b', 'a', 'new'])
  })
})

describe('movePanel', () => {
  it('moves an id one slot in either direction', () => {
    expect(movePanel(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c'])
    expect(movePanel(['a', 'b', 'c'], 'b', 1)).toEqual(['a', 'c', 'b'])
  })

  it('refuses to move past either end', () => {
    expect(movePanel(['a', 'b'], 'a', -1)).toEqual(['a', 'b'])
    expect(movePanel(['a', 'b'], 'b', 1)).toEqual(['a', 'b'])
  })

  it('leaves an unknown id alone', () => {
    expect(movePanel(['a', 'b'], 'zzz', 1)).toEqual(['a', 'b'])
  })
})

describe('reorderVisiblePanel', () => {
  const catalogue = [{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'd' }]

  it('moves a panel one slot when nothing is hidden', () => {
    expect(reorderVisiblePanel(catalogue, {}, 'b', 1)).toEqual([
      'a',
      'c',
      'b',
      'd',
    ])
  })

  /* The reason this is not just movePanel: 'c' is hidden, so moving 'b' down
     has to land it past 'c' and below 'd'. Swapping with the next entry in the
     list would put 'b' after a panel nobody can see, and the screen would not
     change -- a button that looks broken. */
  it('moves past a hidden neighbour to the next visible one', () => {
    const order = reorderVisiblePanel(catalogue, { hidden: ['c'] }, 'b', 1)
    expect(order.filter((id) => id !== 'c')).toEqual(['a', 'd', 'b'])
  })

  /* And the reason it is not computed from the visible panels alone: a hidden
     panel that fell off the stored order would come back at the end rather
     than where it was. */
  it('keeps hidden panels in the stored order', () => {
    const order = reorderVisiblePanel(catalogue, { hidden: ['c'] }, 'b', 1)
    expect(order).toContain('c')
    expect(order).toHaveLength(4)
  })

  it('returns the current order unchanged at either end', () => {
    expect(reorderVisiblePanel(catalogue, {}, 'a', -1)).toEqual([
      'a',
      'b',
      'c',
      'd',
    ])
    expect(reorderVisiblePanel(catalogue, {}, 'd', 1)).toEqual([
      'a',
      'b',
      'c',
      'd',
    ])
  })

  it('ignores a panel that is not visible', () => {
    expect(reorderVisiblePanel(catalogue, { hidden: ['b'] }, 'b', 1)).toEqual([
      'a',
      'b',
      'c',
      'd',
    ])
  })

  it('builds on an order already stored', () => {
    const once = reorderVisiblePanel(catalogue, {}, 'a', 1)
    expect(once).toEqual(['b', 'a', 'c', 'd'])
    expect(reorderVisiblePanel(catalogue, { order: once }, 'a', 1)).toEqual([
      'b',
      'c',
      'a',
      'd',
    ])
  })
})
