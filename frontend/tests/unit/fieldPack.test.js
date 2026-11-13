import { describe, expect, it } from 'vitest'
import {
  addressLine,
  indexPack,
  itemsByDate,
  moneyLabel,
  orderTasks,
  packExpired,
  packWeeks,
  planItemText,
  savedWhen,
  searchCustomers,
  searchKey,
  shortDate,
  telHref,
  weekdayName,
} from '@/utils/fieldPack'

const DAY = 86400000

describe('packExpired', () => {
  const now = Date.UTC(2026, 10, 13, 9)

  it('keeps a pack inside its shelf life', () => {
    expect(packExpired(now - 13 * DAY, 14, now)).toBe(false)
  })

  it('drops one past it', () => {
    expect(packExpired(now - 15 * DAY, 14, now)).toBe(true)
  })

  it('treats a pack with no readable age or limit as expired', () => {
    expect(packExpired(undefined, 14, now)).toBe(true)
    expect(packExpired('yesterday', 14, now)).toBe(true)
    expect(packExpired(now, undefined, now)).toBe(true)
    expect(packExpired(now, 0, now)).toBe(true)
  })
})

describe('indexPack', () => {
  const pack = {
    organizations: [
      { name: 'Impala Platinum', organization_name: 'Impala Platinum' },
      { name: 'ORG-0002', organization_name: 'Canyon Coal' },
    ],
    contacts: [
      { name: 'C1', company_name: 'Impala Platinum' },
      { name: 'C2', company_name: 'Canyon Coal' },
      { name: 'C3', company_name: 'Somebody Else' },
      { name: 'C4', company_name: null },
    ],
    deals: [
      { name: 'D1', organization: 'Impala Platinum' },
      { name: 'D2', organization: 'ORG-0002' },
    ],
    history: [{ name: 'H1', organization: 'Impala Platinum' }],
    notes: [
      { name: 'N1', reference_doctype: 'CRM Deal', reference_docname: 'D2' },
      {
        name: 'N2',
        reference_doctype: 'CRM Organization',
        reference_docname: 'Impala Platinum',
      },
      { name: 'N3', reference_doctype: 'CRM Deal', reference_docname: 'gone' },
    ],
  }
  const index = indexPack(pack)

  it('files a contact under the customer its company names', () => {
    expect(index.contacts.get('Impala Platinum').map((c) => c.name)).toEqual([
      'C1',
    ])
  })

  it('matches a company written as the display name of a renamed record', () => {
    expect(index.contacts.get('ORG-0002').map((c) => c.name)).toEqual(['C2'])
  })

  it('leaves out people at no customer in the pack', () => {
    const filed = [...index.contacts.values()].flat().map((c) => c.name)
    expect(filed).not.toContain('C3')
    expect(filed).not.toContain('C4')
  })

  it('files a note on a deal under the deal’s customer', () => {
    expect(index.notes.get('ORG-0002').map((n) => n.name)).toEqual(['N1'])
    expect(index.notes.get('Impala Platinum').map((n) => n.name)).toEqual([
      'N2',
    ])
  })

  it('survives a pack with nothing in it', () => {
    const empty = indexPack(null)
    expect(empty.byName.size).toBe(0)
    expect(empty.deals.size).toBe(0)
  })
})

describe('searchCustomers', () => {
  const orgs = [
    { name: 'Anglo American Platinum', address: { city: 'Rustenburg' } },
    { name: 'Impala Platinum', territory: 'North West' },
    { name: 'Sasol Secunda', address: { city: 'Secunda' } },
    { name: 'Northam Platinum (Zondereinde)' },
    { name: 'Glencore Impunzi' },
  ]
  const names = (query, limit) =>
    searchCustomers(orgs, query, limit).rows.map((org) => org.name)

  it('returns everything, capped, when nothing is typed', () => {
    const out = searchCustomers(orgs, '  ', 2)
    expect(out.rows.length).toBe(2)
    expect(out.total).toBe(5)
  })

  it('puts a name that starts with the query ahead of one that contains it', () => {
    expect(names('imp')).toEqual(['Impala Platinum', 'Glencore Impunzi'])
  })

  it('needs every word, in any order', () => {
    expect(names('platinum impala')).toEqual(['Impala Platinum'])
  })

  it('finds a customer by town or territory', () => {
    expect(names('rustenburg')).toEqual(['Anglo American Platinum'])
    expect(names('north west')).toEqual(['Impala Platinum'])
  })

  it('ignores case, accents and punctuation', () => {
    expect(names('ZONDEREINDE')).toEqual(['Northam Platinum (Zondereinde)'])
    expect(searchKey('Café-Münster (Pty.) Ltd')).toBe('cafe munster pty ltd')
  })

  it('reports how many matched beyond the cap', () => {
    const out = searchCustomers(orgs, 'platinum', 1)
    expect(out.rows.length).toBe(1)
    expect(out.total).toBe(3)
  })
})

describe('plans', () => {
  const plans = [
    {
      week_start: '2026-11-09',
      items: [
        { name: 'a', planned_date: '2026-11-10' },
        { name: 'b', planned_date: '2026-11-10' },
        { name: 'c', planned_date: '2026-11-13' },
      ],
    },
    { week_start: '2026-11-02', items: [] },
  ]

  it('groups items by their day and remembers the week', () => {
    const days = itemsByDate(plans)
    expect(days.get('2026-11-10').map((i) => i.name)).toEqual(['a', 'b'])
    expect(days.get('2026-11-13')[0].week_start).toBe('2026-11-09')
    expect(days.get('2026-11-11')).toBeUndefined()
  })

  it('lists the weeks the device holds, oldest first', () => {
    expect(packWeeks(plans)).toEqual(['2026-11-02', '2026-11-09'])
    expect(packWeeks(undefined)).toEqual([])
  })
})

describe('orderTasks', () => {
  const tasks = [
    { title: 'Undated' },
    { title: 'Next week', due_date: '2026-11-20 09:00:00' },
    { title: 'Overdue', due_date: '2026-11-10 17:00:00' },
    { title: 'Today', due_date: '2026-11-13 08:00:00' },
  ]

  it('puts the soonest first and the undated last', () => {
    expect(orderTasks(tasks, '2026-11-13').map((t) => t.title)).toEqual([
      'Overdue',
      'Today',
      'Next week',
      'Undated',
    ])
  })

  it('marks only what fell due before today as overdue', () => {
    const out = orderTasks(tasks, '2026-11-13')
    expect(out.filter((t) => t.overdue).map((t) => t.title)).toEqual([
      'Overdue',
    ])
  })
})

describe('display helpers', () => {
  it('builds a dialable link and refuses what is not a number', () => {
    expect(telHref('+27 (0)14 592-1234')).toBe('tel:+270145921234')
    expect(telHref('014 592 1234')).toBe('tel:0145921234')
    expect(telHref('n/a')).toBe('')
    expect(telHref(null)).toBe('')
  })

  it('joins an address, skipping blanks', () => {
    expect(
      addressLine({
        address_line1: 'Shaft 4 Road',
        address_line2: ' ',
        city: 'Rustenburg',
        country: 'South Africa',
      }),
    ).toBe('Shaft 4 Road, Rustenburg, South Africa')
    expect(addressLine(null)).toBe('')
  })

  it('names days without the device zone moving them', () => {
    expect(weekdayName('2026-11-13')).toBe('Fri')
    expect(shortDate('2026-11-13')).toBe('13 Nov')
    expect(shortDate('2026-11-13 23:59:00', 'en-GB')).toBe('13 Nov')
  })

  it('shows money, and nothing for no value', () => {
    expect(moneyLabel(125000, 'ZAR', 'en-ZA')).toMatch(/125.000/)
    expect(moneyLabel(0, 'ZAR')).toBe('')
    expect(moneyLabel(1200, 'NOT-A-CODE', 'en-GB')).toBe('NOT-A-CODE 1,200')
  })

  it('says when the pack was saved relative to now', () => {
    const now = new Date(2026, 10, 13, 15, 0).getTime()
    expect(savedWhen(new Date(2026, 10, 13, 8, 14).getTime(), now).day).toBe(
      'today',
    )
    expect(savedWhen(new Date(2026, 10, 12, 23, 50).getTime(), now).day).toBe(
      'yesterday',
    )
    expect(savedWhen(new Date(2026, 10, 9, 8, 0).getTime(), now).day).toBe(
      'date',
    )
    expect(savedWhen(null, now)).toBeNull()
  })
})

describe('planItemText', () => {
  it('leads with the note, as the planner does', () => {
    expect(planItemText({ note: 'Quote follow-up' }, 'Visit')).toEqual({
      title: 'Quote follow-up',
      detail: '',
    })
  })

  it('adds the outcome when it says something the note did not', () => {
    expect(
      planItemText(
        { note: 'Routine site visit', outcome: 'Checked the valves' },
        'Visit',
      ),
    ).toEqual({ title: 'Routine site visit', detail: 'Checked the valves' })
  })

  it('does not say the same sentence twice', () => {
    expect(
      planItemText(
        {
          note: 'Dropped off four actuators',
          outcome: 'Dropped off four actuators',
        },
        'Delivery',
      ),
    ).toEqual({ title: 'Dropped off four actuators', detail: '' })
  })

  it('shows the whole account when the note is only its first line', () => {
    const outcome =
      'Replaced the 350mm knife gate. Buyer wants a quote for two more by Friday.'
    expect(
      planItemText(
        { note: 'Replaced the 350mm knife gate. Buyer wants…', outcome },
        'Visit',
      ),
    ).toEqual({ title: 'Visit', detail: outcome })
  })

  it('falls back to what it was given when there is no note', () => {
    expect(planItemText({ outcome: 'Done' }, 'Impala Platinum')).toEqual({
      title: 'Impala Platinum',
      detail: 'Done',
    })
    expect(planItemText(null, 'Visit')).toEqual({ title: 'Visit', detail: '' })
  })
})
