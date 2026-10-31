import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'

/**
 * main.js sends a lapsed session to /login from frappe-ui's `resourceFetcher`,
 * which only the resources read. `call()` goes straight to frappeRequest, and
 * it is what sending an email, posting a comment, the planner and creating a
 * deal use: after an overnight lapse those failed with a permission toast and
 * no redirect. The bare 'frappe-ui' specifier resolves to the compat shim, so
 * this imports `call` exactly the way app code does.
 */
const assign = vi.fn()
const realLocation = window.location

/* The session cookie as the page would read it. Stubbed rather than written:
   the code under test only reads it, and a getter cannot outlive the test. */
function sessionCookie(value) {
  vi.spyOn(document, 'cookie', 'get').mockReturnValue(value)
}

function answer(status, body) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  )
}

// Each test re-imports frappe-ui. The first import transforms all of it, which
// takes seconds on a CI runner and must not count against a test's 5s limit.
beforeAll(() => import('frappe-ui'), 60_000)

beforeEach(() => {
  // The redirect is once per page load; each test gets a fresh page.
  vi.resetModules()
  assign.mockClear()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: {
      pathname: '/crm/deals/CRM-DEAL-2026-00001',
      search: '',
      hash: '#emails',
      hostname: 'localhost',
      assign,
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: realLocation,
  })
  vi.restoreAllMocks()
})

describe('call() on a lapsed session', () => {
  it('sends the rep to log in, back to the page they were on', async () => {
    sessionCookie('user_id=Guest')
    answer(403, { exc_type: 'PermissionError', session_expired: 1 })
    const { call } = await import('frappe-ui')

    await expect(
      call('frappe.core.doctype.communication.email.make', {}),
    ).rejects.toMatchObject({ exc_type: 'PermissionError' })

    await vi.waitFor(() => expect(assign).toHaveBeenCalledOnce())
    expect(assign).toHaveBeenCalledWith(
      '/login?redirect-to=' +
        encodeURIComponent('/crm/deals/CRM-DEAL-2026-00001#emails'),
    )
  })

  it('redirects once when several calls fail together', async () => {
    sessionCookie('user_id=Guest')
    answer(403, { exc_type: 'PermissionError', session_expired: 1 })
    const { call } = await import('frappe-ui')

    await Promise.allSettled([call('a.b.c'), call('d.e.f')])
    await vi.waitFor(() => expect(assign).toHaveBeenCalled())
    expect(assign).toHaveBeenCalledOnce()
  })

  it('clears the offline cache, and only then leaves the page', async () => {
    // whoever logs in next may not be this person, and a navigation abandons
    // an IndexedDB clear still in progress
    let finishClearing
    const clearOfflineCache = vi.fn(
      () => new Promise((resolve) => (finishClearing = resolve)),
    )
    vi.doMock('@/utils/offlineCache', () => ({ clearOfflineCache }))
    sessionCookie('user_id=Guest')
    answer(403, { exc_type: 'PermissionError', session_expired: 1 })
    const { call } = await import('frappe-ui')

    await expect(call('a.b.c')).rejects.toMatchObject({
      exc_type: 'PermissionError',
    })
    vi.doUnmock('@/utils/offlineCache')

    expect(clearOfflineCache).toHaveBeenCalledOnce()
    expect(assign).not.toHaveBeenCalled()
    finishClearing()
    await vi.waitFor(() => expect(assign).toHaveBeenCalledOnce())
  })

  it('leaves a real permission refusal on a live session alone', async () => {
    sessionCookie('user_id=rep%40example.com')
    answer(403, { exc_type: 'PermissionError' })
    const { call } = await import('frappe-ui')

    await expect(call('crm.api.doc.get_data')).rejects.toMatchObject({
      exc_type: 'PermissionError',
    })
    expect(assign).not.toHaveBeenCalled()
  })

  it('passes a successful answer through untouched', async () => {
    answer(200, { message: { ok: 1 } })
    const { call } = await import('frappe-ui')

    await expect(call('crm.api.ping')).resolves.toEqual({ ok: 1 })
  })
})
