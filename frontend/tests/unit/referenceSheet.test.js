import { describe, expect, it } from 'vitest'
import {
  boxCentre,
  boxStyle,
  cellValue,
  highlightBoxes,
  pdfPageUrl,
  safeFileUrl,
} from '@/utils/referenceSheet'

describe('boxStyle', () => {
  it('turns PDF points into percentages of the page', () => {
    expect(boxStyle([59.5, 84.2, 119, 168.4], 595, 842)).toEqual({
      left: '10.000%',
      top: '10.000%',
      width: '10.000%',
      height: '10.000%',
    })
  })

  it('pads, and clamps the pad to the page', () => {
    const style = boxStyle([0, 0, 595, 842], 595, 842, 5)
    expect(style).toEqual({
      left: '0.000%',
      top: '0.000%',
      width: '100.000%',
      height: '100.000%',
    })
  })

  it('refuses a missing, malformed or inside-out box', () => {
    expect(boxStyle(null, 595, 842)).toBeNull()
    expect(boxStyle([1, 2, 3], 595, 842)).toBeNull()
    expect(boxStyle([10, 10, 5, 20], 595, 842)).toBeNull()
    expect(boxStyle([1, 2, 3, 'x'], 595, 842)).toBeNull()
    expect(boxStyle([1, 2, 3, 4], 0, 842)).toBeNull()
  })
})

describe('boxCentre', () => {
  it('is the vertical middle of the box as a share of the page', () => {
    expect(boxCentre([0, 400, 10, 442], 842)).toBeCloseTo(0.5, 2)
    expect(boxCentre(null, 842)).toBe(0)
  })
})

describe('highlightBoxes', () => {
  const reference = {
    page_width: 595,
    page_height: 842,
    bbox: [10, 20, 300, 30],
    highlight: [0, 2],
    cells: [
      { label: 'Flange OD', value: '285.0', bbox: [100, 20, 110, 30] },
      { label: 'PCD', value: '240.0', bbox: [120, 20, 130, 30] },
      {
        label: 'Hole',
        value: '',
        status: 'questioned',
        bbox: [140, 20, 150, 30],
      },
      { label: 'Nominal bore', value: '150 mm' },
    ],
  }

  it('marks the row, the quoted cells and every questioned cell', () => {
    expect(highlightBoxes(reference).map((box) => box.key)).toEqual([
      'guide-row',
      'guide-column',
      'row',
      'cell-0',
      'cell-2',
    ])
    expect(
      highlightBoxes({ ...reference, highlight: [1] }).map((b) => b.key),
    ).toEqual(['guide-row', 'guide-column', 'row', 'cell-1', 'cell-2'])
  })

  it('tells a questioned cell apart', () => {
    const questioned = highlightBoxes(reference).find((b) => b.key === 'cell-2')
    expect(questioned.kind).toBe('questioned')
  })

  it('runs the guides from the page edges up to the row and the quoted cell', () => {
    const [rowGuide, columnGuide] = highlightBoxes(reference)
    // row box 10..300 pt padded by 1 on a 595 pt page: ends at 301 pt
    expect(rowGuide.style.left).toBe('0%')
    expect(parseFloat(rowGuide.style.width)).toBeCloseTo((301 / 595) * 100, 2)
    // cell 20..30 pt padded by 1.5 on an 842 pt page: ends at 31.5 pt
    expect(columnGuide.style.top).toBe('0%')
    expect(parseFloat(columnGuide.style.height)).toBeCloseTo(
      (31.5 / 842) * 100,
      2,
    )
  })

  it('draws no column guide when every cell is quoted', () => {
    const all = { ...reference, highlight: [0, 1, 2, 3] }
    expect(highlightBoxes(all).map((b) => b.key)).not.toContain('guide-column')
  })

  it('skips cells with no box and survives an empty reference', () => {
    expect(
      highlightBoxes({ ...reference, highlight: [3] }).map((b) => b.key),
    ).toEqual(['guide-row', 'row', 'cell-2'])
    expect(highlightBoxes(null)).toEqual([])
  })
})

describe('cellValue', () => {
  it('joins the unit and withholds a questioned value', () => {
    expect(cellValue({ value: '285.0', unit: 'mm' })).toBe('285.0 mm')
    expect(cellValue({ value: 'M20', unit: '' })).toBe('M20')
    expect(cellValue({ value: '36.0', status: 'questioned' })).toBeNull()
  })
})

describe('pdfPageUrl and safeFileUrl', () => {
  it('links a site file at the page', () => {
    expect(pdfPageUrl('/private/files/drilling.pdf', 2)).toBe(
      '/private/files/drilling.pdf#page=2',
    )
    expect(pdfPageUrl('/files/x.pdf', 'nope')).toBe('/files/x.pdf')
  })

  it('links nothing that is not a site file', () => {
    expect(pdfPageUrl('javascript:alert(1)', 1)).toBe('')
    expect(pdfPageUrl('https://example.com/x.pdf', 1)).toBe('')
    expect(safeFileUrl('//evil.example/x.png')).toBe('')
    expect(safeFileUrl('/private/files/p-1.png')).toBe('/private/files/p-1.png')
  })
})
