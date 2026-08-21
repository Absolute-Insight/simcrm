import { describe, it, expect } from 'vitest'
import { quiet } from '@/utils/quiet'

describe('quiet', () => {
  it('swallows a rejection', async () => {
    await expect(quiet(Promise.reject(new Error('boom')))).resolves.toBe(
      undefined,
    )
  })

  it('passes a resolved value through', async () => {
    await expect(quiet(Promise.resolve(42))).resolves.toBe(42)
  })

  it('accepts a non-promise', async () => {
    await expect(quiet(undefined)).resolves.toBe(undefined)
  })
})
