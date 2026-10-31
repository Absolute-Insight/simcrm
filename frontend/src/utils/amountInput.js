const SUFFIXES = { k: 3, m: 6, b: 9 }

/**
 * Read an amount typed into a grid that displays amounts in compact notation.
 *
 * The Sales Targets grid shows "300K" and "1.5M", so that is what people type
 * back. Stripping every non-digit made "300K" a target of 300. A trailing K, M
 * or B now scales the number, read with the display locale's decimal separator
 * because that is the notation the cell showed ("1,3M" in en-ZA). Without a
 * suffix the number is read as before: "." is the decimal point and commas are
 * grouping, which is what the cell holds while focused. Any other letter makes
 * the text not a number, rather than a different one.
 *
 * @param {string} text what was typed
 * @param {string} [locale] the locale the grid formats with (the browser's by default)
 * @returns {number} the amount, 0 for blank text, NaN for text that is not an amount
 */
export function parseAmount(text, locale) {
  const typed = String(text ?? '').replace(/\s/g, '')
  if (typed === '') return 0
  const match = /^([^a-z]*)([kmb])?$/i.exec(typed)
  if (!match) return NaN
  let digits = match[1]
  const suffix = match[2]?.toLowerCase()
  if (suffix) {
    const { group, decimal } = separators(locale)
    digits = digits.split(group).join('').replace(decimal, '.')
  }
  digits = digits.replace(/[^\d.-]/g, '')
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(digits)) return NaN
  // shifted in the exponent, not multiplied: 1.1 * 1000 is 1100.0000000000002
  return Number(suffix ? `${digits}e${SUFFIXES[suffix]}` : digits)
}

function separators(locale) {
  const parts = new Intl.NumberFormat(locale).formatToParts(1234567.5)
  return {
    group: parts.find((p) => p.type === 'group')?.value ?? ',',
    decimal: parts.find((p) => p.type === 'decimal')?.value ?? '.',
  }
}
