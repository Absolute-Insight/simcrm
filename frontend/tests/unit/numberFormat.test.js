import { afterEach, describe, expect, it } from 'vitest'
import { flt, formatCurrency } from '@/utils/numberFormat.js'

describe('flt', () => {
  const sysdefaults = window.sysdefaults
  afterEach(() => (window.sysdefaults = sysdefaults))

  // Field.vue and SidePanelLayout.vue show a Currency field as the formatted
  // string and parse whatever is left in the box with flt(). With a space
  // group separator the symbol strip kept only the last digit group, so
  // nudging the cents of "ZAR 50 221.12" saved 221.13.
  it('parses a space-grouped amount back through its currency symbol', () => {
    window.sysdefaults = {
      currency: 'ZAR',
      number_format: '# ###.##',
      currency_precision: 2,
    }
    const shown = formatCurrency(50221.12, '', 'ZAR', null)
    expect(shown).toBe('ZAR 50 221.12')
    expect(flt(shown.replace(/2$/, '3'))).toBe(50221.13)
    expect(flt('ZAR 1 250 000')).toBe(1250000)
    expect(flt('ZAR -50 300.00')).toBe(-50300)
  })

  it('keeps the decimal comma of a "# ###,##" format', () => {
    window.sysdefaults = { number_format: '# ###,##' }
    expect(flt('ZAR 50 221,13')).toBe(50221.13)
  })

  it('still parses a comma-grouped amount and a bare number', () => {
    window.sysdefaults = { number_format: '#,###.##' }
    expect(flt('$ 50,221.13')).toBe(50221.13)
    expect(flt('50,221.13')).toBe(50221.13)
    expect(flt('12.5%')).toBe(12.5)
    expect(flt('')).toBe(0)
  })
})
