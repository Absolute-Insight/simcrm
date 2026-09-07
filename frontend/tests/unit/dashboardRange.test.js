import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// dashboard.ts takes dayjs from frappe-ui, whose entry drags in the whole
// resource layer; the real dayjs is all the test needs.
vi.mock('frappe-ui', async () => ({ dayjs: (await import('dayjs')).default }))

import { getLastXDays, parseDateRange } from '@/utils/dashboard'

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
