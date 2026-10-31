import { afterEach, describe, expect, it, vi } from 'vitest'
import { setConfig } from 'frappe-ui'
import { useEventNotifications } from '@/data/notifications'

/* Notifications -> Events lists the user's open events that have not ended.
   useEvent's list resource is cached for the session, and frappe-ui returns a
   cached resource with the filters it was first built with, so the "now" in
   `ends_on >= now` used to be the first open's for the rest of the day. */

vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@example.com' }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (name) => ({ full_name: name }) }),
}))
vi.mock('@/utils', () => ({ sameArrayContents: () => true }))
vi.mock('@/data/userSettings', () => ({
  getUserSettings: async () => ({}),
  useUserSettings: () => ({ save: async () => ({}) }),
}))

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

afterEach(() => {
  vi.useRealTimers()
})

describe('useEventNotifications', () => {
  it('filters on the site clock at each open, once per open', async () => {
    const sent = []
    setConfig('systemTimezone', 'Africa/Johannesburg')
    setConfig('resourceFetcher', async ({ params }) => {
      if (params?.doctype === 'Event') sent.push(params.filters.ends_on)
      return []
    })

    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-30T06:00:00Z')) // 08:00 on site
    useEventNotifications()
    await settle()
    vi.setSystemTime(new Date('2026-10-30T13:00:00Z')) // 15:00 on site
    useEventNotifications()
    await settle()

    expect(sent).toEqual([
      ['>=', '2026-10-30 08:00:00'],
      ['>=', '2026-10-30 15:00:00'],
    ])
  })
})
