import { afterEach, describe, expect, it, vi } from 'vitest'
import { getConfig, setConfig } from 'frappe-ui'

vi.mock('@/stores/users', () => ({ usersStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))

const { formatDate } = await import('@/utils')

describe('formatDate', () => {
  const sysdefaults = window.sysdefaults
  const systemTimezone = getConfig('systemTimezone')
  const localTimezone = getConfig('localTimezone')
  afterEach(() => {
    window.sysdefaults = sysdefaults
    setConfig('systemTimezone', systemTimezone)
    setConfig('localTimezone', localTimezone)
  })

  function asUserWestOfSite() {
    window.sysdefaults = { date_format: 'dd-mm-yyyy', time_format: 'HH:mm' }
    setConfig('systemTimezone', 'Africa/Johannesburg') // the site, +02:00
    setConfig('localTimezone', 'Europe/London') // the user's Time Zone
  }

  // List views format Date columns with formatDate(value, '', true). A
  // calendar date has no time to convert: read as midnight in the site's
  // zone and shifted to London it fell on the previous day.
  it('shows a Date field as its calendar date in any user timezone', () => {
    asUserWestOfSite()
    expect(formatDate('2026-10-30', '', true, false)).toBe('30-10-2026')
  })

  it('still converts a Datetime to the user timezone', () => {
    asUserWestOfSite()
    expect(formatDate('2026-10-30 01:00:00', '', true, true)).toBe(
      '29-10-2026 23:00',
    )
  })
})
