import { beforeEach, describe, expect, it, vi } from 'vitest'
// Loaded once here so the per-test fresh copies below are not each paying to
// transform it.
import 'frappe-ui'

/* The inbox endpoint returns the newest page only (crm.api.notifications
   PAGE_LENGTH), so the unread badge has to come from the server's count: a
   count of the unread rows that came back stops at the page size. */

let server

async function loadStore() {
  vi.resetModules()
  const { setConfig } = await import('frappe-ui')
  setConfig('resourceFetcher', async ({ url }) => {
    server.calls.push(url)
    const answer = server[url]
    if (answer instanceof Error) throw answer
    return answer
  })
  const store = await import('@/stores/notifications')
  await settle()
  return store
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

const unreadRow = (i) => ({
  creation: `2026-10-30 09:00:${String(i % 60).padStart(2, '0')}`,
  read: 0,
  notification_type_doc: `D${i}`,
})

beforeEach(() => {
  server = {
    calls: [],
    'crm.api.notifications.get_notifications': Array.from(
      { length: 50 },
      (_, i) => unreadRow(i),
    ),
    'crm.api.notifications.get_unread_count': 300,
  }
})

describe('the unread notifications badge', () => {
  it('shows the whole inbox count, not the unread rows on the page', async () => {
    const { unreadNotificationsCount } = await loadStore()
    expect(unreadNotificationsCount.value).toBe('300')
  })

  it('is refreshed whenever the inbox is', async () => {
    const { notifications, unreadNotificationsCount } = await loadStore()
    server['crm.api.notifications.get_unread_count'] = 0
    await notifications.reload()
    await settle()
    expect(unreadNotificationsCount.value).toBe(0)
    expect(
      server.calls.filter(
        (url) => url === 'crm.api.notifications.get_unread_count',
      ),
    ).toHaveLength(2)
  })

  it('says it is unavailable when the count never loaded', async () => {
    server['crm.api.notifications.get_unread_count'] = new Error('down')
    const { unreadCountUnavailable, unreadNotificationsCount } =
      await loadStore()
    expect(unreadNotificationsCount.value).toBe(0)
    expect(unreadCountUnavailable.value).toBe(true)
  })
})
