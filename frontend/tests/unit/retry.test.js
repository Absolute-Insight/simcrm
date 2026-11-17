import { describe, expect, it, vi } from 'vitest'
import { retryWithBackoff } from '@/utils/retry'

const noWait = () => Promise.resolve()

describe('retryWithBackoff', () => {
  it('returns the first success without waiting', async () => {
    const wait = vi.fn(noWait)
    const attempt = vi.fn().mockResolvedValue('users')
    await expect(
      retryWithBackoff(attempt, { delays: [500, 1500], wait }),
    ).resolves.toBe('users')
    expect(attempt).toHaveBeenCalledTimes(1)
    expect(wait).not.toHaveBeenCalled()
  })

  it('recovers from a blip, waiting the given delays in order', async () => {
    const wait = vi.fn(noWait)
    const attempt = vi
      .fn()
      .mockRejectedValueOnce(new Error('502'))
      .mockRejectedValueOnce(new Error('timeout'))
      .mockResolvedValue('users')
    await expect(
      retryWithBackoff(attempt, { delays: [500, 1500], wait }),
    ).resolves.toBe('users')
    expect(attempt).toHaveBeenCalledTimes(3)
    expect(wait.mock.calls.map(([ms]) => ms)).toEqual([500, 1500])
  })

  it('gives up after the last delay with the last error', async () => {
    const attempt = vi
      .fn()
      .mockRejectedValueOnce(new Error('first'))
      .mockRejectedValueOnce(new Error('second'))
      .mockRejectedValue(new Error('last'))
    await expect(
      retryWithBackoff(attempt, { delays: [1, 1], wait: noWait }),
    ).rejects.toThrow('last')
    expect(attempt).toHaveBeenCalledTimes(3)
  })

  it('does not retry an error a retry cannot fix', async () => {
    // A PermissionError means "not a CRM user"; retrying only delays the
    // Not Permitted page.
    const denied = { exc_type: 'PermissionError' }
    const attempt = vi.fn().mockRejectedValue(denied)
    await expect(
      retryWithBackoff(attempt, {
        delays: [500, 1500],
        wait: noWait,
        shouldRetry: (e) => e?.exc_type !== 'PermissionError',
      }),
    ).rejects.toBe(denied)
    expect(attempt).toHaveBeenCalledTimes(1)
  })

  it('tries exactly once with no delays', async () => {
    const attempt = vi.fn().mockRejectedValue(new Error('down'))
    await expect(retryWithBackoff(attempt)).rejects.toThrow('down')
    expect(attempt).toHaveBeenCalledTimes(1)
  })
})
