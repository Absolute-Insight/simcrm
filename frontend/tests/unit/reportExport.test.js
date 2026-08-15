import { EMPTY_CELL, UTF8_BOM, formatCell, toCsv } from '@/utils/reportExport'

const COLUMNS = [
  { key: 'stage', label: 'Stage', type: 'text' },
  { key: 'deals', label: 'Deals', type: 'number' },
  { key: 'total_value', label: 'Expected value', type: 'currency' },
]

/* Intl output is locale- and ICU-version-dependent, so the assertions below
   check what the formatter was asked to do (a symbol is present, grouping
   happened, the fraction was dropped) rather than an exact glyph sequence. */
describe('formatCell', () => {
  it('renders an absent measure as a dash rather than a zero', () => {
    expect(formatCell(null, 'currency', 'USD')).toBe(EMPTY_CELL)
    expect(formatCell(undefined, 'number')).toBe(EMPTY_CELL)
    expect(formatCell('', 'text')).toBe(EMPTY_CELL)
  })

  it('keeps a real zero', () => {
    expect(formatCell(0, 'number')).toBe('0')
  })

  it('renders currency with a symbol and no cents', () => {
    const rendered = formatCell(1250000, 'currency', 'USD')
    expect(rendered).toMatch(/\$/)
    expect(rendered).toMatch(/1.250.000/)
    expect(rendered).not.toMatch(/\.00/)
  })

  it('honours the base currency it is given rather than a locale default', () => {
    expect(formatCell(1000, 'currency', 'EUR')).toMatch(/€/)
    expect(formatCell(1000, 'currency', 'INR')).toMatch(/₹/)
  })

  it('degrades to a code-prefixed number for an unusable currency code', () => {
    const rendered = formatCell(1500, 'currency', 'not-a-code')
    expect(rendered).toMatch(/NOT-A-CODE/)
    expect(rendered).toMatch(/1.500/)
  })

  it('groups plain numbers and drops the fraction', () => {
    expect(formatCell(1234567, 'number')).toMatch(/1.234.567/)
    expect(formatCell(12.6, 'number')).toBe('13')
  })

  it('suffixes percentages and keeps one decimal', () => {
    expect(formatCell(42, 'percent')).toBe('42%')
    expect(formatCell(42.55, 'percent')).toBe('42.6%')
  })

  it('passes text through untouched', () => {
    expect(formatCell('Qualification', 'text')).toBe('Qualification')
  })

  it('does not render NaN when a measure column comes back as prose', () => {
    expect(formatCell('n/a', 'currency', 'USD')).toBe('n/a')
    expect(formatCell('n/a', 'percent')).toBe('n/a')
  })
})

describe('toCsv', () => {
  it('opens with a UTF-8 BOM so Excel reads it as UTF-8', () => {
    expect(toCsv(COLUMNS, [])).toContain(UTF8_BOM)
    expect(toCsv(COLUMNS, []).indexOf(UTF8_BOM)).toBe(0)
  })

  it('emits only a header for an empty row set', () => {
    const csv = toCsv(COLUMNS, [])
    expect(csv.slice(UTF8_BOM.length)).toBe('Stage,Deals,Expected value')
  })

  it('tolerates missing columns and rows', () => {
    expect(toCsv(null, null)).toBe(UTF8_BOM + '')
    expect(toCsv(undefined, undefined)).toBe(UTF8_BOM + '')
  })

  it('names the unit in the currency header instead of in every cell', () => {
    const csv = toCsv(COLUMNS, [{ total_value: 1250000 }], 'ZAR')
    expect(csv).toContain('Expected value (ZAR)')
    // the cell itself stays a bare number so the spreadsheet can sum it
    expect(csv).toContain('1250000')
  })

  it('separates records with CRLF and adds no trailing separator', () => {
    const csv = toCsv(COLUMNS, [
      { stage: 'Qualification', deals: 3, total_value: 10 },
      { stage: 'Demo', deals: 1, total_value: 20 },
    ])
    const records = csv.slice(UTF8_BOM.length).split('\r\n')
    expect(records).toHaveLength(3)
    expect(records[2]).toBe('Demo,1,20')
  })

  it('writes an empty field for a value the row is missing', () => {
    const csv = toCsv(COLUMNS, [{ stage: 'Demo' }])
    expect(csv.slice(UTF8_BOM.length).split('\r\n')[1]).toBe('Demo,,')
  })

  describe('quoting', () => {
    const cell = (value) =>
      toCsv([{ key: 'v', label: 'v', type: 'text' }], [{ v: value }])
        .slice(UTF8_BOM.length)
        .split('\r\n')[1]

    it('quotes a value containing a comma', () => {
      expect(cell('Acme, Inc.')).toBe('"Acme, Inc."')
    })

    it('doubles and quotes an embedded double quote', () => {
      expect(cell('the "big" one')).toBe('"the ""big"" one"')
    })

    it('quotes a value containing a newline', () => {
      expect(cell('line one\nline two')).toBe('"line one\nline two"')
    })

    it('quotes a value containing a carriage return', () => {
      // a bare CR is a record separator to RFC 4180 readers, so leaving it
      // unquoted silently splits the row in two
      expect(cell('line one\rline two')).toBe('"line one\rline two"')
    })

    it('leaves an ordinary value unquoted', () => {
      expect(cell('Qualification')).toBe('Qualification')
    })
  })

  describe('formula injection', () => {
    const cell = (value) =>
      toCsv([{ key: 'v', label: 'v', type: 'text' }], [{ v: value }])
        .slice(UTF8_BOM.length)
        .split('\r\n')[1]

    it.each([
      ['=1+1', "'=1+1"],
      ['+1+1', "'+1+1"],
      ['-1+1', "'-1+1"],
      ['@SUM(A1)', "'@SUM(A1)"],
    ])('neutralises a cell starting with %s', (value, expected) => {
      expect(cell(value)).toBe(expected)
    })

    it('neutralises a leading tab, which the parser eats before evaluating', () => {
      expect(cell('\t=1+1')).toBe("'\t=1+1")
    })

    it('neutralises a formula smuggled in a column header', () => {
      const csv = toCsv([{ key: 'v', label: '=cmd|calc', type: 'text' }], [])
      expect(csv.slice(UTF8_BOM.length)).toBe("'=cmd|calc")
    })

    it('leaves negative figures numeric, since a number cannot be a formula', () => {
      const csv = toCsv(
        [{ key: 'gap', label: 'Gap', type: 'currency' }],
        [{ gap: -45000.5 }],
      )
      expect(csv.slice(UTF8_BOM.length).split('\r\n')[1]).toBe('-45000.5')
    })
  })

  it('passes non-ASCII through so the BOM has something to declare', () => {
    const csv = toCsv(
      [{ key: 'v', label: 'Röportaj', type: 'text' }],
      [{ v: '株式会社ハラダ — Ωmega' }],
    )
    expect(csv).toContain('Röportaj')
    expect(csv).toContain('株式会社ハラダ — Ωmega')
  })
})
