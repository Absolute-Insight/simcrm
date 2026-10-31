import { describe, it, expect } from 'vitest'
import { nextPageLength } from '@/utils/listPaging'

describe('nextPageLength', () => {
  it('grows by one step below the cap', () => {
    expect(nextPageLength(20, 20, 1000)).toBe(40)
  })

  it('stops at the cap rather than asking past it', () => {
    // 990 + 20 would be 1010, which the server answers with 1000 rows anyway
    expect(nextPageLength(990, 20, 1000)).toBe(1000)
  })

  it('says there is nothing more once the cap is reached', () => {
    expect(nextPageLength(1000, 20, 1000)).toBeNull()
    expect(nextPageLength(1040, 20, 1000)).toBeNull()
  })

  it('treats a missing cap as none', () => {
    expect(nextPageLength(1000, 100, undefined)).toBe(1100)
  })
})
