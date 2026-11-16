import { beforeEach, describe, expect, it, vi } from 'vitest'

const { call } = vi.hoisted(() => ({ call: vi.fn() }))
vi.mock('frappe-ui', () => ({ call }))

import {
  cachedEmailBody,
  fetchEmailBody,
  forgetEmailBodies,
  rememberEmailBody,
} from '@/composables/useEmailBody'

beforeEach(() => {
  forgetEmailBodies()
  call.mockReset()
})

describe('useEmailBody', () => {
  it('keeps the most recent bodies, not every one ever opened', () => {
    for (let i = 0; i < 45; i++) rememberEmailBody(`c-${i}`, `<p>${i}</p>`)
    expect(cachedEmailBody('c-0')).toBeUndefined()
    expect(cachedEmailBody('c-4')).toBeUndefined()
    expect(cachedEmailBody('c-5')).toBe('<p>5</p>')
    expect(cachedEmailBody('c-44')).toBe('<p>44</p>')
  })

  it('does not keep a failure: the next ask goes to the server again', async () => {
    call.mockRejectedValueOnce(new Error('Email not found'))
    await expect(fetchEmailBody('c-1')).rejects.toThrow('Email not found')
    call.mockResolvedValueOnce({ content: '<p>ok</p>' })
    await expect(fetchEmailBody('c-1')).resolves.toBe('<p>ok</p>')
    await expect(fetchEmailBody('c-1')).resolves.toBe('<p>ok</p>')
    expect(call).toHaveBeenCalledTimes(2)
  })

  it('ignores what is not a body', () => {
    rememberEmailBody('c-1', undefined)
    rememberEmailBody('', '<p>x</p>')
    expect(cachedEmailBody('c-1')).toBeUndefined()
  })
})

describe('useEmailBody and who is logged in', () => {
  const loginAs = (user) => {
    document.cookie = `user_id=${user}; path=/`
  }

  it('is not served to another user who logs in from another tab', () => {
    loginAs('rep-a@example.com')
    rememberEmailBody('c-1', '<p>A can read this</p>')
    expect(cachedEmailBody('c-1')).toBe('<p>A can read this</p>')
    loginAs('rep-b@example.com')
    expect(cachedEmailBody('c-1')).toBeUndefined()
    loginAs('rep-a@example.com')
    expect(cachedEmailBody('c-1')).toBeUndefined()
  })

  it('drops an answer to a request made for the previous user', async () => {
    loginAs('rep-a@example.com')
    let answer
    call.mockReturnValueOnce(new Promise((r) => (answer = r)))
    const request = fetchEmailBody('c-2')
    loginAs('rep-b@example.com')
    answer({ content: '<p>for A</p>' })
    await request
    expect(cachedEmailBody('c-2')).toBeUndefined()
  })

  it('is cleared with the offline cache on logout or a lost session', async () => {
    loginAs('rep-a@example.com')
    rememberEmailBody('c-3', '<p>body</p>')
    const { clearOfflineCache } = await import('@/utils/offlineCache')
    await clearOfflineCache()
    expect(cachedEmailBody('c-3')).toBeUndefined()
  })
})
