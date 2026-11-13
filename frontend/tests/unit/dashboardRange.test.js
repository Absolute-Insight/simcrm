import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// dashboard.ts asks frappe-ui for the site's timezone only; its entry drags in
// the whole resource layer, so the test answers that one question itself.
const site = vi.hoisted(() => ({ timezone: null }))
vi.mock('frappe-ui', () => ({
  getConfig: (key) => (key === 'systemTimezone' ? site.timezone : undefined),
}))

import {
  formatRange,
  getLastXDays,
  parseDateRange,
  presetDaysFor,
} from '@/utils/dashboard'

/**
 * The server treats `[from, to]` as inclusive (`date_diff + 1` days, see
 * `period_windows` in crm/api/dashboard.py), so a range of today-30..today is
 * 31 days under a "Last 30 Days" label, and quota was pro-rated over 31 days
 * while the manager compared against a month.
 */
describe('getLastXDays', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 6, 12)) // 6 Sep 2026, local noon
  })
  afterEach(() => vi.useRealTimers())

  function inclusiveDays(range) {
    const [from, to] = parseDateRange(range)
    const ms =
      Date.UTC(
        ...to
          .split('-')
          .map(Number)
          .map((n, i) => (i === 1 ? n - 1 : n)),
      ) -
      Date.UTC(
        ...from
          .split('-')
          .map(Number)
          .map((n, i) => (i === 1 ? n - 1 : n)),
      )
    return ms / 86_400_000 + 1
  }

  it('ends today', () => {
    expect(parseDateRange(getLastXDays(30))[1]).toBe('2026-09-06')
  })

  it('spans exactly N inclusive days for every preset', () => {
    for (const days of [7, 30, 60, 90]) {
      expect(inclusiveDays(getLastXDays(days))).toBe(days)
    }
  })

  it('"Last 30 Days" on 6 Sep starts on 8 Aug, not 7 Aug', () => {
    expect(getLastXDays(30)).toBe('2026-08-08,2026-09-06')
  })
})

/**
 * The period is sent to a server that reports on the site's calendar days, and
 * the page's own "today" is the site's. Built from the browser clock, the
 * window ended a day short of it for part of every day in another zone.
 */
describe('getLastXDays on the site calendar', () => {
  const hostZone = process.env.TZ
  beforeEach(() => {
    vi.useFakeTimers()
    site.timezone = 'Africa/Johannesburg' // +02:00
  })
  afterEach(() => {
    vi.useRealTimers()
    site.timezone = null
    if (hostZone === undefined) delete process.env.TZ
    else process.env.TZ = hostZone
  })

  it('ends on the site day when the browser is still on the day before', () => {
    process.env.TZ = 'America/Los_Angeles'
    // 23:30 UTC on the 13th: 01:30 on the 14th on site, 15:30 on the 13th in LA
    vi.setSystemTime(new Date('2026-11-13T23:30:00Z'))
    expect(getLastXDays(30)).toBe('2026-10-16,2026-11-14')
  })

  it('ends on the site day when the browser is already on the day after', () => {
    process.env.TZ = 'Pacific/Auckland'
    // 21:30 UTC on the 13th: 23:30 on the 13th on site, the 14th in Auckland
    vi.setSystemTime(new Date('2026-11-13T21:30:00Z'))
    expect(getLastXDays(7)).toBe('2026-11-07,2026-11-13')
  })

  it('crosses a month and a year end by the calendar', () => {
    vi.setSystemTime(new Date('2027-01-02T10:00:00Z'))
    expect(getLastXDays(7)).toBe('2026-12-27,2027-01-02')
    expect(getLastXDays(90)).toBe('2026-10-05,2027-01-02')
  })

  it('names the preset a range is today, and none once the day has moved on', () => {
    vi.setSystemTime(new Date('2026-11-13T10:00:00Z'))
    const range = getLastXDays(30)
    expect(presetDaysFor(range, [7, 30, 60, 90])).toBe(30)
    expect(presetDaysFor(range.split(','), [7, 30, 60, 90])).toBe(30)
    expect(presetDaysFor('2026-01-01,2026-01-05', [7, 30, 60, 90])).toBe(null)
    vi.setSystemTime(new Date('2026-11-14T10:00:00Z'))
    expect(presetDaysFor(range, [7, 30, 60, 90])).toBe(null)
  })
})

/**
 * `new Date('2026-10-01')` is UTC midnight, which is still 30 September
 * anywhere west of Greenwich -- so the label named the day before the range the
 * figures were for, on the Dashboard's preset button and the printed Reports
 * sheet alike. The query dates were right; only the words were wrong.
 */
describe('formatRange', () => {
  afterEach(() => vi.unstubAllEnvs())

  it('names the day it was given in a browser west of UTC', () => {
    vi.stubEnv('TZ', 'America/Sao_Paulo') // -03:00, no DST in 2026
    const sameYear = new Date().getFullYear() === 2026
    const firstOfOctober = new Date(2026, 9, 1).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: sameYear ? undefined : 'numeric',
    })
    expect(formatRange('2026-10-01')).toBe(firstOfOctober)
  })
})
