import {
  skeletonCellWidth,
  skeletonLineWidths,
  skeletonTableColumns,
} from '@/utils/skeletonShapes'

describe('skeletonLineWidths', () => {
  it('returns nothing for a non-positive or unusable count', () => {
    expect(skeletonLineWidths(0)).toEqual([])
    expect(skeletonLineWidths(-3)).toEqual([])
    expect(skeletonLineWidths(undefined)).toEqual([])
    expect(skeletonLineWidths('nope')).toEqual([])
  })

  it('gives a single line the full measure', () => {
    expect(skeletonLineWidths(1)).toEqual(['100%'])
  })

  it('shortens the last line of a paragraph', () => {
    const widths = skeletonLineWidths(3)
    expect(widths).toHaveLength(3)
    const tail = parseFloat(widths[2])
    widths
      .slice(0, 2)
      .forEach((w) => expect(parseFloat(w)).toBeGreaterThan(tail))
  })

  it('varies the body lines so the right edge is ragged', () => {
    const widths = skeletonLineWidths(4).slice(0, 3)
    expect(new Set(widths).size).toBeGreaterThan(1)
  })

  it('is deterministic — the same count always renders the same bars', () => {
    expect(skeletonLineWidths(5)).toEqual(skeletonLineWidths(5))
  })

  it('floors a fractional count', () => {
    expect(skeletonLineWidths(2.9)).toHaveLength(2)
  })

  it('keeps every width a percentage string', () => {
    skeletonLineWidths(9).forEach((w) => expect(w).toMatch(/^\d+%$/))
  })
})

describe('skeletonTableColumns', () => {
  it('builds a spec from a plain column count', () => {
    const cols = skeletonTableColumns(3)
    expect(cols).toHaveLength(3)
    cols.forEach((col) => {
      expect(col.width).toMatch(/^\d+%$/)
      expect(col.headWidth).toMatch(/^\d+%$/)
    })
  })

  it('falls back to one column for an unusable count', () => {
    expect(skeletonTableColumns(0)).toHaveLength(1)
    expect(skeletonTableColumns(undefined)).toHaveLength(1)
  })

  it('left-aligns the label column and right-aligns the measures', () => {
    expect(skeletonTableColumns(4).map((c) => c.align)).toEqual([
      'left',
      'right',
      'right',
      'right',
    ])
  })

  it('follows the report column types when given a real spec', () => {
    const cols = skeletonTableColumns([
      { type: 'text' },
      { type: 'currency' },
      { type: 'text' },
    ])
    expect(cols.map((c) => c.align)).toEqual(['left', 'right', 'left'])
  })

  it('lets an explicit align win over the type', () => {
    const cols = skeletonTableColumns([{ type: 'currency', align: 'left' }])
    expect(cols[0].align).toBe('left')
  })

  it('makes the header bar narrower than the data bar', () => {
    skeletonTableColumns(5).forEach((col) => {
      expect(parseFloat(col.headWidth)).toBeLessThan(parseFloat(col.width))
    })
  })

  it('gives the label column more room than the measures', () => {
    const cols = skeletonTableColumns(4)
    cols.slice(1).forEach((col) => {
      expect(parseFloat(col.width)).toBeLessThan(parseFloat(cols[0].width))
    })
  })

  it('survives holes in a supplied spec', () => {
    expect(skeletonTableColumns([null, undefined])).toHaveLength(2)
  })
})

describe('skeletonCellWidth', () => {
  const column = { width: '60%' }

  it('leaves the first row at full width', () => {
    expect(skeletonCellWidth(column, 0)).toBe('60%')
  })

  it('shortens later rows so the grid is not uniform', () => {
    const widths = [0, 1, 2, 3].map((i) => skeletonCellWidth(column, i))
    expect(new Set(widths).size).toBeGreaterThan(1)
    widths.forEach((w) => expect(parseFloat(w)).toBeLessThanOrEqual(60))
  })

  it('is deterministic per row', () => {
    expect(skeletonCellWidth(column, 7)).toBe(skeletonCellWidth(column, 7))
  })

  it('cycles rather than shrinking to nothing on a long table', () => {
    expect(skeletonCellWidth(column, 40)).toBe(skeletonCellWidth(column, 0))
  })

  it('falls back when the column has no usable width', () => {
    expect(skeletonCellWidth({}, 0)).toBe('60%')
    expect(skeletonCellWidth(null, 2)).toBe('60%')
  })

  it('treats a negative row index as the first row', () => {
    expect(skeletonCellWidth(column, -1)).toBe(skeletonCellWidth(column, 0))
  })
})
