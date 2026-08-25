import { describe, expect, it } from 'vitest'
import { formatDelta, ringDash } from '@/utils/gauge'

describe('ringDash', () => {
  it('fills the ring proportionally to the clamped percentage', () => {
    const C = 2 * Math.PI * 58
    const { pct, dasharray } = ringDash(33, 58)
    expect(pct).toBe(33)
    const [filled, rest] = dasharray.split(' ').map(Number)
    expect(filled).toBeCloseTo(C * 0.33, 1)
    expect(filled + rest).toBeCloseTo(C, 1)
  })

  it('clamps to the 0-100 band', () => {
    expect(ringDash(140, 58).pct).toBe(100)
    expect(ringDash(-20, 58).pct).toBe(0)
  })

  it('treats non-numeric input as zero', () => {
    expect(ringDash(null, 58).pct).toBe(0)
    expect(ringDash('n/a', 58).pct).toBe(0)
    const [filled] = ringDash(undefined, 58).dasharray.split(' ').map(Number)
    expect(filled).toBe(0)
  })

  it('accepts numeric strings', () => {
    expect(ringDash('66.5', 58).pct).toBe(66.5)
  })
})

describe('formatDelta', () => {
  it('formats small deltas with sign and one decimal', () => {
    expect(formatDelta(33, '%')).toBe('+33%')
    expect(formatDelta(-4.25, '%')).toBe('−4.3%')
  })

  it('rounds three-digit magnitudes to integers', () => {
    expect(formatDelta(123.7, '%')).toBe('+124%')
  })

  it('clamps past 999 as a comparison', () => {
    expect(formatDelta(1721.4, '%')).toBe('>999%')
    expect(formatDelta(-1721.4, '%')).toBe('<−999%')
  })

  it('returns empty for zero or absent deltas', () => {
    expect(formatDelta(0, '%')).toBe('')
    expect(formatDelta(null, '%')).toBe('')
    expect(formatDelta(undefined, '%')).toBe('')
  })
})
