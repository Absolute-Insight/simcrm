/**
 * Geometry for the loading skeletons — pure, so it can be unit-tested.
 *
 * Nothing outside `components/ui/` should be reaching for skeleton
 * measurements; the two components there are the intended consumers.
 *
 * The widths are fixed tables rather than `Math.random()`: a skeleton that
 * reshuffles its bars on every re-render reads as a glitch, and a random
 * layout cannot be asserted in a test.
 */

/* Ragged right edge of a paragraph, as a percentage of the container. Real
   prose almost fills the measure; a perfectly flush block of bars looks like a
   table, not text. */
const BODY_LINE_WIDTHS = [100, 97, 92, 99, 94, 96]

/* The last line of a paragraph stops early. Which is the single strongest cue
   that the placeholder is standing in for text. */
const TAIL_LINE_WIDTHS = [62, 48, 71, 55]

/* Body-cell fills, as a percentage of the cell. Columns of numbers are short
   and of uneven length; a column of identical bars reads as a progress grid. */
const CELL_WIDTHS = [54, 66, 47, 68, 59, 62]

/* Per-row shortening of the cell fill. Without it every row is identical and
   the table reads as a loading bar chart rather than as data. */
const ROW_SCALES = [1, 0.86, 0.94, 0.78, 1, 0.9, 0.83, 0.97]

function toCount(value, fallback = 0) {
  const n = Math.floor(Number(value))
  return Number.isFinite(n) && n > 0 ? n : fallback
}

/**
 * Widths for `lines` stacked text bars, in source order.
 * @returns {string[]} CSS width values, one per line.
 */
export function skeletonLineWidths(lines) {
  const count = toCount(lines)
  if (count === 0) return []
  if (count === 1) return ['100%']

  const widths = []
  for (let i = 0; i < count - 1; i++) {
    widths.push(`${BODY_LINE_WIDTHS[i % BODY_LINE_WIDTHS.length]}%`)
  }
  widths.push(`${TAIL_LINE_WIDTHS[(count - 1) % TAIL_LINE_WIDTHS.length]}%`)
  return widths
}

function columnAlign(column, index) {
  if (column.align === 'left' || column.align === 'right') return column.align
  /* Mirrors the report/quota tables: the first column names the row and every
     other column is a measure, right-aligned against the tabular figures. */
  if (column.type) return column.type === 'text' ? 'left' : 'right'
  return index === 0 ? 'left' : 'right'
}

/**
 * Normalise a column count, or a real column spec, into bar geometry.
 * @param {number|Array<{type?: string, align?: string}>} columns
 * @returns {Array<{align: string, width: string, headWidth: string}>}
 */
export function skeletonTableColumns(columns) {
  const source = Array.isArray(columns)
    ? columns
    : Array.from({ length: toCount(columns, 1) }, () => ({}))

  return source.map((column, index) => {
    const spec = column || {}
    const align = columnAlign(spec, index)
    /* The label column carries a name, so it runs long; measures do not. */
    const width = index === 0 ? 70 : CELL_WIDTHS[index % CELL_WIDTHS.length]
    return {
      align,
      width: `${width}%`,
      /* Headers are short uppercase labels — never as wide as the data. */
      headWidth: `${Math.round(width * 0.62)}%`,
    }
  })
}

/**
 * The fill width of one body cell, varied by row so the grid is not uniform.
 * @param {{width: string}} column A column from `skeletonTableColumns`.
 * @param {number} rowIndex Zero-based row.
 * @returns {string} A CSS percentage.
 */
export function skeletonCellWidth(column, rowIndex) {
  const base = parseFloat(column?.width)
  if (!Number.isFinite(base)) return '60%'
  const index = toCount(rowIndex + 1, 1) - 1
  return `${Math.round(base * ROW_SCALES[index % ROW_SCALES.length])}%`
}
