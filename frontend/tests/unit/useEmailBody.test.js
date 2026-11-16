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
