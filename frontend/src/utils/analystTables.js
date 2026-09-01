/**
 * Shape an Analyst table for the screen and for CSV.
 *
 * The server hands back `{ key, title, source, columns, rows, period, note,
 * error }` with typed columns (text, int, currency, percent, date, month).
 * This turns that into display cells with the report formatter, so a figure
 * on the Analyst page reads exactly as it does on the Reports page.
 */
import { EMPTY_CELL, formatCell, toCsv } from '@/utils/reportExport'

const MONTH_NAMES = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

/** `2026-08` → `Aug 2026`; anything else is returned as is. */
export function monthLabel(value) {
  const match = /^(\d{4})-(\d{2})$/.exec(String(value ?? ''))
  if (!match) return value === null || value === undefined ? '' : String(value)
  const month = Number(match[2])
  if (month < 1 || month > 12) return String(value)
  return `${MONTH_NAMES[month - 1]} ${match[1]}`
}

function reportType(type) {
  if (type === 'int') return 'number'
  if (type === 'month' || type === 'date') return 'text'
  return type || 'text'
}

/**
 * @param {object} table one table from `ask_analyst`
 * @param {string} currency base currency code
 * @returns {{ key, title, source, note, error, columns: [{key,label,align}],
 *   rows: string[][], csv: () => string }}
 */
export function formatTable(table, currency = '') {
  const columns = (table?.columns || []).map((column) => ({
    key: column.key,
    label: column.label,
    align: ['int', 'currency', 'percent'].includes(column.type)
      ? 'right'
      : 'left',
  }))

  const rows = (table?.rows || []).map((row) =>
    (table?.columns || []).map((column) => {
      const value = row?.[column.key]
      if (column.type === 'month') return monthLabel(value)
      if (value === null || value === undefined || value === '')
        return EMPTY_CELL
      return formatCell(value, reportType(column.type), currency)
    }),
  )

  return {
    key: table?.key || '',
    title: table?.title || '',
    source: table?.source || 'CRM',
    note: table?.note || '',
    error: table?.error || null,
    columns,
    rows,
    csv: () =>
      toCsv(
        (table?.columns || []).map((column) => ({
          key: column.key,
          label: column.label,
          type: reportType(column.type),
        })),
        table?.rows || [],
        currency,
      ),
  }
}
