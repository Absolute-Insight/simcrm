import { describe, expect, it } from 'vitest'
import { parseAmount } from '@/utils/amountInput'

describe('parseAmount', () => {
  it('reads the compact notation the grid displays', () => {
    expect(parseAmount('300K', 'en-US')).toBe(300000)
    expect(parseAmount('300k', 'en-US')).toBe(300000)
    expect(parseAmount('1.5M', 'en-US')).toBe(1500000)
    expect(parseAmount('2B', 'en-US')).toBe(2000000000)
    expect(parseAmount('1.1K', 'en-US')).toBe(1100)
    expect(parseAmount('250 K', 'en-US')).toBe(250000)
  })

  it('reads a compact figure with the display locale decimal separator', () => {
    // what en-ZA's compact notation shows for 1,250,000
    expect(parseAmount('1,3M', 'en-ZA')).toBe(1300000)
    expect(parseAmount('1.3M', 'en-ZA')).toBe(1300000)
    expect(parseAmount('1,300K', 'en-US')).toBe(1300000)
  })

  it('reads plain digits as before, with commas as grouping', () => {
    expect(parseAmount('120000', 'en-US')).toBe(120000)
    expect(parseAmount('250,000', 'en-US')).toBe(250000)
    expect(parseAmount('1500.5', 'en-ZA')).toBe(1500.5)
    expect(parseAmount('$5,000', 'en-US')).toBe(5000)
  })

  it('treats blank as zero', () => {
    expect(parseAmount('', 'en-US')).toBe(0)
    expect(parseAmount('   ', 'en-US')).toBe(0)
    expect(parseAmount(null, 'en-US')).toBe(0)
  })

  it('refuses text that is not an amount rather than saving a different one', () => {
    for (const text of [
      '300KK',
      'abc',
      'K',
      '5000abc',
      'R5000',
      '1.2.3',
      '-',
    ]) {
      expect(parseAmount(text, 'en-US'), text).toBeNaN()
    }
  })

  it('keeps the sign, for the caller to refuse', () => {
    expect(parseAmount('-5', 'en-US')).toBe(-5)
    expect(parseAmount('-2K', 'en-US')).toBe(-2000)
  })
})
