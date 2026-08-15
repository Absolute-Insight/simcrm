/**
 * Pure formatting for the Reports page: how one cell reads on screen, and how a
 * whole report serialises to a CSV that Excel opens without lying about it.
 *
 * It lives here rather than inside Reports.vue because the CSV escaping is the
 * part with a security consequence — a spreadsheet treats some cell values as
 * executable — and that is only worth trusting if it is unit-tested.
 *
 * Nothing here calls `__()`: every label it is handed (report titles, column
 * labels) is already translated by `crm.api.reports`, and the only strings it
 * authors itself are symbols.
 */

/** What an absent measure prints as, so a blank cell is never mistaken for 0. */
export const EMPTY_CELL = '—'

/**
 * Excel, LibreOffice and Sheets evaluate a cell whose text begins with one of
 * these as a formula on open, so an organisation literally named
 * `=HYPERLINK("http://evil","payroll")` runs on the reader's machine. Tab and
 * CR are in the set because both are consumed before the parse, exposing
 * whatever character follows them.
 */
const FORMULA_PREFIX = /^[=+\-@\t\r]/

/**
 * RFC 4180 quoting triggers. `\r` belongs here as well as `\n`: a lone CR is a
 * record separator to some readers, so an unquoted one silently splits a row.
 */
const NEEDS_QUOTING = /[",\n\r]/

/**
 * Excel only detects UTF-8 in a CSV when the file opens with a byte-order mark;
 * without it, every non-ASCII name arrives mojibaked.
 */
export const UTF8_BOM = '﻿'

/* Intl formatters are expensive to construct and these are built per cell, so
   they are memoised on the options that distinguish them. */
const formatterCache = new Map()

function getFormatter(key, options) {
  let formatter = formatterCache.get(key)
  if (!formatter) {
    formatter = new Intl.NumberFormat(undefined, options)
    formatterCache.set(key, formatter)
  }
  return formatter
}

/* An unknown or malformed currency code makes Intl throw rather than degrade,
   and a report is not worth losing over a misconfigured setting — fall back to
   a grouped number with the raw code in front of it. */
function currencyFormatter(currency) {
  const code = String(currency || '').toUpperCase()
  const key = `currency:${code}`
  if (formatterCache.has(key)) return formatterCache.get(key)

  let formatter
  try {
    formatter = new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: code,
      maximumFractionDigits: 0,
    })
  } catch {
    const plain = getFormatter('number', { maximumFractionDigits: 0 })
    formatter = {
      format: (value) =>
        code ? `${code} ${plain.format(value)}` : plain.format(value),
    }
  }
  formatterCache.set(key, formatter)
  return formatter
}

/**
 * Render one cell for the screen.
 *
 * @param {*} value raw value from the report row
 * @param {string} type column type declared by the registry: text, number,
 *   currency or percent
 * @param {string} currency ISO code of the CRM base currency; every currency
 *   column is normalised to it server-side
 * @returns {string}
 */
export function formatCell(value, type, currency = '') {
  if (value === null || value === undefined || value === '') return EMPTY_CELL

  if (type === 'currency' || type === 'number' || type === 'percent') {
    const number = Number(value)
    /* A measure column that came back as prose is a backend change, not a
       reason to render NaN at the user. */
    if (!Number.isFinite(number)) return String(value)

    if (type === 'currency') return currencyFormatter(currency).format(number)
    if (type === 'percent') {
      return `${getFormatter('percent', { maximumFractionDigits: 1 }).format(number)}%`
    }
    return getFormatter('number', { maximumFractionDigits: 0 }).format(number)
  }

  return String(value)
}

/**
 * The CSV header for a column. Currency figures are exported unformatted so the
 * spreadsheet still sees numbers it can sum; the unit therefore has to be
 * stated once, in the header, rather than glued to every cell.
 */
function columnLabel(column, currency) {
  const label = String(column?.label ?? '')
  if (column?.type === 'currency' && currency) return `${label} (${currency})`
  return label
}

function csvField(value) {
  if (value === null || value === undefined) return ''

  let text = String(value)
  /* Numbers are produced by the aggregation layer, never typed by a user, and
     cannot carry a formula. Neutralising them anyway would prefix every
     negative figure — a `gap` column is full of them — and Excel would import
     the whole column as text. So the guard applies to authored values only. */
  if (typeof value !== 'number' && FORMULA_PREFIX.test(text)) {
    text = `'${text}`
  }

  return NEEDS_QUOTING.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/**
 * Serialise a report to CSV text, BOM included, ready to become a Blob.
 *
 * Rows are joined with CRLF per RFC 4180. There is no trailing separator: a
 * naive `split('\r\n')` would otherwise report one phantom empty record.
 *
 * @param {Array<{key: string, label: string, type?: string}>} columns
 * @param {Array<Object>} rows
 * @param {string} currency ISO code appended to currency column headers
 * @returns {string}
 */
export function toCsv(columns, rows, currency = '') {
  const cols = Array.isArray(columns) ? columns : []
  const lines = [
    cols.map((col) => csvField(columnLabel(col, currency))).join(','),
  ]

  for (const row of Array.isArray(rows) ? rows : []) {
    lines.push(cols.map((col) => csvField(row?.[col.key])).join(','))
  }

  return UTF8_BOM + lines.join('\r\n')
}
