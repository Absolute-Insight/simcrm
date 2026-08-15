import {
  addDays,
  dedupeProposals,
  groupItemsByDay,
  isBeforeHorizon,
  mondayOf,
  moveItemToDate,
  planDiff,
  referenceNames,
  referenceRoute,
  rollupItems,
  rollupTotals,
  toSavePayload,
  todayInTimeZone,
  weekDayCells,
} from '@/utils/planner'

/* Shaped exactly like crm.api.rep_plan.get_plan's response for a real week:
   child `name`s present, matcher-owned fields present, one manual override. */
const GET_PLAN = {
  name: 'PLAN-0007',
  user: 'rep@example.com',
  week_start: '2026-08-10',
  modified: '2026-08-12 09:14:03.221114',
  items: [
    {
      name: '1a2b3c',
      activity_type: 'Call',
      planned_date: '2026-08-10',
      note: 'Follow up on pricing',
      reference_doctype: 'CRM Deal',
      reference_docname: '000012',
      status: 'Done',
      fulfilled_by_doctype: 'CRM Call Log',
      fulfilled_by: 'CALL-0031',
      manual_override: 0,
      suggestion: 'SUG-0004',
    },
    {
      name: '4d5e6f',
      activity_type: 'Call',
      planned_date: '2026-08-11',
      note: 'Intro call',
      reference_doctype: 'CRM Lead',
      reference_docname: '000045',
      status: 'Missed',
      fulfilled_by_doctype: null,
      fulfilled_by: null,
      manual_override: 1,
      suggestion: null,
    },
    {
      name: '7g8h9i',
      activity_type: 'Task',
      planned_date: '2026-08-14',
      note: 'Send the proposal',
      reference_doctype: 'CRM Deal',
      reference_docname: '000012',
      status: 'Planned',
      fulfilled_by_doctype: null,
      fulfilled_by: null,
      manual_override: 0,
      suggestion: 'SUG-0009',
    },
  ],
  rollup: {
    Call: { planned: 2, done: 1, missed: 1 },
    Task: { planned: 1, done: 0, missed: 0 },
  },
}

describe('mondayOf', () => {
  it('leaves a Monday where it is', () => {
    expect(mondayOf('2026-08-10')).toBe('2026-08-10')
  })

  it('walks a Sunday back to the Monday that opened its week', () => {
    // 2026-08-16 is a Sunday; it belongs to the week that started on the 10th,
    // not to the one starting the next day.
    expect(mondayOf('2026-08-16')).toBe('2026-08-10')
  })

  it('walks every other weekday back to the same Monday', () => {
    const week = [
      '2026-08-11',
      '2026-08-12',
      '2026-08-13',
      '2026-08-14',
      '2026-08-15',
      '2026-08-16',
    ]
    week.forEach((day) => expect(mondayOf(day)).toBe('2026-08-10'))
  })

  it('crosses a month and a year boundary', () => {
    expect(mondayOf('2026-03-01')).toBe('2026-02-23')
    expect(mondayOf('2027-01-01')).toBe('2026-12-28')
  })

  it('accepts a Date and an ISO datetime, and refuses junk', () => {
    expect(mondayOf(new Date(2026, 7, 16))).toBe('2026-08-10')
    expect(mondayOf('2026-08-16 23:45:00')).toBe('2026-08-10')
    expect(mondayOf('')).toBeNull()
    expect(mondayOf(undefined)).toBeNull()
  })

  it('is not moved by a DST transition in the host zone', () => {
    // Europe/London springs forward on 2026-03-29 (a Sunday). Local-time date
    // maths across that boundary is where the off-by-a-day used to appear.
    expect(mondayOf('2026-03-29')).toBe('2026-03-23')
    expect(mondayOf('2026-03-30')).toBe('2026-03-30')
  })
})

describe('addDays', () => {
  it('moves forwards and backwards across a month end', () => {
    expect(addDays('2026-08-31', 1)).toBe('2026-09-01')
    expect(addDays('2026-09-01', -1)).toBe('2026-08-31')
    expect(addDays('2026-08-10', 7)).toBe('2026-08-17')
  })

  it('returns null for an unparseable date', () => {
    expect(addDays('nope', 1)).toBeNull()
  })
})

describe('todayInTimeZone', () => {
  // 2026-08-17T01:30Z: already Monday in Auckland, still Sunday in New York.
  const instant = new Date('2026-08-17T01:30:00Z')

  it('reads the calendar date of the zone it is given', () => {
    expect(todayInTimeZone('Pacific/Auckland', instant)).toBe('2026-08-17')
    expect(todayInTimeZone('America/New_York', instant)).toBe('2026-08-16')
    expect(todayInTimeZone('UTC', instant)).toBe('2026-08-17')
  })

  it('puts the two sides of that boundary in different weeks', () => {
    expect(mondayOf(todayInTimeZone('Pacific/Auckland', instant))).toBe(
      '2026-08-17',
    )
    expect(mondayOf(todayInTimeZone('America/New_York', instant))).toBe(
      '2026-08-10',
    )
  })

  it('falls back to the host zone when the zone is missing or unknown', () => {
    expect(todayInTimeZone('', instant)).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(todayInTimeZone('Mars/Olympus_Mons', instant)).toMatch(
      /^\d{4}-\d{2}-\d{2}$/,
    )
  })
})

describe('weekDayCells', () => {
  it('lays out seven days from the Monday, flagging today and the weekend', () => {
    const cells = weekDayCells('2026-08-10', '2026-08-12')
    expect(cells.map((c) => c.date)).toEqual([
      '2026-08-10',
      '2026-08-11',
      '2026-08-12',
      '2026-08-13',
      '2026-08-14',
      '2026-08-15',
      '2026-08-16',
    ])
    expect(cells.filter((c) => c.isToday).map((c) => c.date)).toEqual([
      '2026-08-12',
    ])
    expect(cells.filter((c) => c.isWeekend).map((c) => c.index)).toEqual([5, 6])
    expect(cells.filter((c) => c.isPast).map((c) => c.index)).toEqual([0, 1])
  })

  it('normalises a mid-week start to its Monday', () => {
    expect(weekDayCells('2026-08-13', '2026-08-13')[0].date).toBe('2026-08-10')
  })

  it('marks no day as today when the week is not the current one', () => {
    expect(
      weekDayCells('2026-08-10', '2026-09-01').some((c) => c.isToday),
    ).toBe(false)
  })
})

describe('groupItemsByDay', () => {
  const days = weekDayCells('2026-08-10', '2026-08-12').map((c) => c.date)

  it('keys every column, including the empty ones', () => {
    const { byDay } = groupItemsByDay(GET_PLAN.items, days)
    expect(Object.keys(byDay)).toEqual(days)
    expect(byDay['2026-08-10'].map((i) => i.name)).toEqual(['1a2b3c'])
    expect(byDay['2026-08-13']).toEqual([])
  })

  it('keeps the order items arrived in within a day', () => {
    const sameDay = [
      { name: 'a', planned_date: '2026-08-11' },
      { name: 'b', planned_date: '2026-08-11' },
    ]
    expect(
      groupItemsByDay(sameDay, days).byDay['2026-08-11'].map((i) => i.name),
    ).toEqual(['a', 'b'])
  })

  it('collects items dated outside the week instead of dropping them', () => {
    const stray = { name: 'z', planned_date: '2026-07-01' }
    const { byDay, outside } = groupItemsByDay([...GET_PLAN.items, stray], days)
    expect(outside).toEqual([stray])
    expect(Object.values(byDay).flat()).toHaveLength(3)
  })

  it('keys by whatever dates appear when no columns are given', () => {
    const { byDay, outside } = groupItemsByDay(GET_PLAN.items)
    expect(Object.keys(byDay).sort()).toEqual([
      '2026-08-10',
      '2026-08-11',
      '2026-08-14',
    ])
    expect(outside).toEqual([])
  })

  it('survives an empty or missing list', () => {
    expect(groupItemsByDay(null, days).outside).toEqual([])
    expect(Object.values(groupItemsByDay([], days).byDay).flat()).toEqual([])
  })
})

describe('rollupItems / rollupTotals', () => {
  it('reproduces the rollup get_plan returned for the same items', () => {
    expect(rollupItems(GET_PLAN.items)).toEqual(GET_PLAN.rollup)
  })

  it('counts every row as planned, and Done/Missed additionally', () => {
    expect(rollupTotals(GET_PLAN.rollup)).toEqual({
      planned: 3,
      done: 1,
      missed: 1,
    })
    expect(rollupTotals(rollupItems(GET_PLAN.items))).toEqual(
      rollupTotals(GET_PLAN.rollup),
    )
  })

  it('totals an absent rollup as zeros rather than throwing', () => {
    expect(rollupTotals(undefined)).toEqual({ planned: 0, done: 0, missed: 0 })
    expect(rollupTotals({})).toEqual({ planned: 0, done: 0, missed: 0 })
    expect(rollupItems(null)).toEqual({})
  })
})

describe('dedupeProposals', () => {
  const drafts = [
    {
      suggestion: 'SUG-0004',
      activity_type: 'Call',
      planned_date: '2026-08-12',
    },
    {
      suggestion: 'SUG-0011',
      activity_type: 'Task',
      planned_date: '2026-08-12',
    },
  ]

  it('drops a draft whose suggestion is already planned', () => {
    expect(dedupeProposals(drafts, GET_PLAN.items)).toEqual([drafts[1]])
  })

  it('drops it even when the planned copy was moved to another day', () => {
    const moved = [{ ...GET_PLAN.items[0], planned_date: '2026-08-15' }]
    expect(dedupeProposals(drafts, moved)).toEqual([drafts[1]])
  })

  it('keeps a draft whose suggestion is not planned yet', () => {
    expect(dedupeProposals(drafts, [])).toEqual(drafts)
  })

  it('does not re-add the same suggestion twice from one batch', () => {
    const twice = [drafts[0], { ...drafts[0], planned_date: '2026-08-13' }]
    expect(dedupeProposals(twice, [])).toEqual([twice[0]])
  })

  it('falls back to matching what the draft is about when it has no suggestion', () => {
    const anonymous = [
      {
        activity_type: 'Task',
        note: 'Send the proposal',
        reference_doctype: 'CRM Deal',
        reference_docname: '000012',
      },
    ]
    // the same work is already row 7g8h9i, which carries a suggestion, so the
    // suggestion index cannot catch it — the shape index has to.
    const planned = [{ ...GET_PLAN.items[2], suggestion: null }]
    expect(dedupeProposals(anonymous, planned)).toEqual([])
    expect(dedupeProposals(anonymous, [])).toEqual(anonymous)
  })

  it('handles empty inputs', () => {
    expect(dedupeProposals(null, GET_PLAN.items)).toEqual([])
    expect(dedupeProposals([], [])).toEqual([])
  })
})

describe('planDiff', () => {
  it('reports a clean buffer as no change', () => {
    const local = GET_PLAN.items.map((i) => ({ ...i }))
    expect(planDiff(local, GET_PLAN.items)).toEqual({
      added: 0,
      removed: 0,
      changed: 0,
      total: 0,
    })
  })

  it('counts a row without a name as an addition', () => {
    const local = [
      ...GET_PLAN.items,
      { activity_type: 'Email', planned_date: '2026-08-13', status: 'Planned' },
    ]
    expect(planDiff(local, GET_PLAN.items)).toMatchObject({
      added: 1,
      removed: 0,
      changed: 0,
    })
  })

  it('counts a missing stored row as a removal', () => {
    expect(planDiff(GET_PLAN.items.slice(1), GET_PLAN.items)).toMatchObject({
      added: 0,
      removed: 1,
      changed: 0,
    })
  })

  it('counts a reschedule that kept its name as a change, not a churn', () => {
    const local = GET_PLAN.items.map((i) =>
      i.name === '7g8h9i' ? { ...i, planned_date: '2026-08-13' } : i,
    )
    expect(planDiff(local, GET_PLAN.items)).toMatchObject({
      added: 0,
      removed: 0,
      changed: 1,
    })
  })

  it('counts a reschedule that lost its name as a delete plus an insert', () => {
    const local = GET_PLAN.items.map(({ name, ...rest }) =>
      name === '7g8h9i'
        ? { ...rest, planned_date: '2026-08-13' }
        : { name, ...rest },
    )
    expect(planDiff(local, GET_PLAN.items)).toMatchObject({
      added: 1,
      removed: 1,
    })
  })

  it('ignores a change the matcher owns', () => {
    const local = GET_PLAN.items.map((i) =>
      i.name === '7g8h9i' ? { ...i, status: 'Done', manual_override: 1 } : i,
    )
    expect(planDiff(local, GET_PLAN.items).total).toBe(0)
  })

  it('treats a plan with no stored rows as all additions', () => {
    expect(planDiff([{ activity_type: 'Call' }], [])).toMatchObject({
      added: 1,
      removed: 0,
    })
  })
})

describe('moveItemToDate', () => {
  it('moves one item and leaves its identity intact', () => {
    const items = GET_PLAN.items.map((i) => ({ ...i }))
    const moved = moveItemToDate(items, items[2], '2026-08-13')
    expect(moved[2]).toMatchObject({
      name: '7g8h9i',
      suggestion: 'SUG-0009',
      planned_date: '2026-08-13',
    })
    expect(moved[0]).toBe(items[0])
    expect(items[2].planned_date).toBe('2026-08-14')
  })

  it('is a no-op when the day did not change or the target is unusable', () => {
    const items = GET_PLAN.items.map((i) => ({ ...i }))
    expect(moveItemToDate(items, items[2], '2026-08-14')).toBe(items)
    expect(moveItemToDate(items, items[2], null)).toBe(items)
    expect(moveItemToDate(items, null, '2026-08-13')).toBe(items)
  })

  it('moves only the item it was handed when two rows look alike', () => {
    const a = { activity_type: 'Call', planned_date: '2026-08-10' }
    const b = { activity_type: 'Call', planned_date: '2026-08-10' }
    const moved = moveItemToDate([a, b], b, '2026-08-11')
    expect(moved[0].planned_date).toBe('2026-08-10')
    expect(moved[1].planned_date).toBe('2026-08-11')
  })
})

describe('isBeforeHorizon', () => {
  it('accepts a week inside the matcher horizon', () => {
    expect(isBeforeHorizon('2026-08-10', '2026-08-12')).toBe(false)
    expect(isBeforeHorizon('2026-06-22', '2026-08-12')).toBe(false)
  })

  it('refuses a week older than the horizon', () => {
    // eight weeks before 2026-08-12 is 2026-06-17; the Monday of 2026-06-08 is
    // older than that and save_plan would throw.
    expect(isBeforeHorizon('2026-06-08', '2026-08-12')).toBe(true)
  })

  it('lets the horizon Monday itself through, as the server`s strict `<` does', () => {
    // eight weeks before Monday 2026-08-10 is Monday 2026-06-15 exactly.
    expect(isBeforeHorizon('2026-06-15', '2026-08-10')).toBe(false)
    expect(isBeforeHorizon('2026-06-08', '2026-08-10')).toBe(true)
  })

  it('judges the week a mid-week date belongs to, not the date', () => {
    expect(isBeforeHorizon('2026-06-17', '2026-08-12')).toBe(
      isBeforeHorizon('2026-06-15', '2026-08-12'),
    )
  })

  it('does not block when the dates are unusable', () => {
    expect(isBeforeHorizon('', '2026-08-12')).toBe(false)
    expect(isBeforeHorizon('2026-06-08', '')).toBe(false)
  })
})

describe('referenceRoute', () => {
  it('routes a deal and a lead to their own pages', () => {
    expect(referenceRoute(GET_PLAN.items[0])).toEqual({
      name: 'Deal',
      params: { dealId: '000012' },
    })
    expect(referenceRoute(GET_PLAN.items[1])).toEqual({
      name: 'Lead',
      params: { leadId: '000045' },
    })
  })

  it('returns nothing rather than mislabelling an unknown reference', () => {
    expect(
      referenceRoute({
        reference_doctype: 'CRM Task',
        reference_docname: 'T1',
      }),
    ).toBeNull()
    expect(referenceRoute({ reference_doctype: 'CRM Deal' })).toBeNull()
    expect(referenceRoute({})).toBeNull()
    expect(referenceRoute(null)).toBeNull()
  })
})

describe('referenceNames', () => {
  it('collects distinct names per doctype', () => {
    expect(referenceNames(GET_PLAN.items)).toEqual({
      deals: ['000012'],
      leads: ['000045'],
    })
  })

  it('ignores references it cannot resolve', () => {
    expect(
      referenceNames([
        { reference_doctype: 'CRM Task', reference_docname: 'T1' },
        { reference_doctype: 'CRM Deal', reference_docname: null },
        {},
      ]),
    ).toEqual({ deals: [], leads: [] })
  })
})

describe('toSavePayload', () => {
  it('sends only editable fields, and keeps the child name', () => {
    expect(toSavePayload([GET_PLAN.items[0]])).toEqual([
      {
        name: '1a2b3c',
        activity_type: 'Call',
        planned_date: '2026-08-10',
        note: 'Follow up on pricing',
        reference_doctype: 'CRM Deal',
        reference_docname: '000012',
        suggestion: 'SUG-0004',
      },
    ])
  })

  it('omits the name on a row that does not have one yet', () => {
    const [row] = toSavePayload([
      { activity_type: 'Email', planned_date: '2026-08-13' },
    ])
    expect(row).not.toHaveProperty('name')
    expect(row).toMatchObject({ activity_type: 'Email', note: null })
  })
})
