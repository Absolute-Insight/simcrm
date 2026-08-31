import { describe, expect, it } from 'vitest'
import { INTRINSIC_SIZE, intrinsicProps } from '@/components/Icons/_phosphor'

describe('intrinsicProps', () => {
  it('returns the legacy intrinsic size for a known icon', () => {
    expect(intrinsicProps('BellIcon')).toEqual({ width: 16, height: 16 })
  })

  it('preserves the 24px icons rather than flattening everything to 16', () => {
    expect(intrinsicProps('DocumentIcon')).toEqual({ width: 24, height: 24 })
  })

  it('throws on an unknown icon rather than guessing a size', () => {
    expect(() => intrinsicProps('NotAnIcon')).toThrow(/NotAnIcon/)
  })
})

describe('INTRINSIC_SIZE', () => {
  it('has no zero or negative dimensions', () => {
    for (const [name, [w, h]] of Object.entries(INTRINSIC_SIZE)) {
      expect(w, name).toBeGreaterThan(0)
      expect(h, name).toBeGreaterThan(0)
    }
  })
})
