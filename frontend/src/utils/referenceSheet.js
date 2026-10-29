/**
 * Placing a reference-sheet row on its page.
 *
 * The server sends each cited row with its page size in PDF points and the
 * boxes of the row and its cells in the same units, measured from the page's
 * top-left (see crm/api/reference.py). The page image is the page rendered
 * whole, so a box becomes CSS percentages of the image and stays on the cell
 * at any rendered width — phone or desktop, fit or zoomed.
 */

/** A box as `left/top/width/height` percentages of its page, or null. */
export function boxStyle(bbox, pageWidth, pageHeight, pad = 0) {
  if (!Array.isArray(bbox) || bbox.length !== 4) return null
  if (!(pageWidth > 0) || !(pageHeight > 0)) return null
  const [x0, top, x1, bottom] = bbox.map(Number)
  if (![x0, top, x1, bottom].every(Number.isFinite)) return null
  const left = Math.max(0, x0 - pad)
  const up = Math.max(0, top - pad)
  const right = Math.min(pageWidth, x1 + pad)
  const down = Math.min(pageHeight, bottom + pad)
  if (right <= left || down <= up) return null
  const pct = (value, of) => `${((value / of) * 100).toFixed(3)}%`
  return {
    left: pct(left, pageWidth),
    top: pct(up, pageHeight),
    width: pct(right - left, pageWidth),
    height: pct(down - up, pageHeight),
  }
}

/** Where on the page (0–1, from the top) a box sits, to scroll it into view. */
export function boxCentre(bbox, pageHeight) {
  if (!Array.isArray(bbox) || bbox.length !== 4 || !(pageHeight > 0)) return 0
  const centre = (Number(bbox[1]) + Number(bbox[3])) / 2 / pageHeight
  return Number.isFinite(centre) ? Math.min(1, Math.max(0, centre)) : 0
}

/**
 * The marks to draw on the page for a reference: faint guide bands from the
 * page's left edge along the row and from its top edge down the first quoted
 * cell's column (on a dense sheet the cell alone is a speck at "fit page";
 * the bands lead the eye to its row and column headings), the row's outline, each cell the answer quoted, and every
 * cell awaiting confirmation -- those are worth seeing whether or not the
 * answer mentioned them.
 */
export function highlightBoxes(reference) {
  const { page_width: width, page_height: height } = reference || {}
  const quoted = new Set(reference?.highlight || [])
  const cells = reference?.cells || []
  const boxes = []
  const row = boxStyle(reference?.bbox, width, height, 1)
  const firstQuoted = cells.findIndex(
    (cell, index) =>
      quoted.has(index) && cell.status !== 'questioned' && cell.bbox,
  )
  // Each guide stops at the row: run on to the page edge and it crosses the
  // second table of a two-up page and points at the wrong row there.
  const end = (style, start, size) =>
    `${(parseFloat(style[start]) + parseFloat(style[size])).toFixed(3)}%`
  if (row) {
    boxes.push({
      key: 'guide-row',
      kind: 'guide',
      style: { ...row, left: '0%', width: end(row, 'left', 'width') },
    })
  }
  const column =
    firstQuoted >= 0
      ? boxStyle(cells[firstQuoted].bbox, width, height, 1.5)
      : null
  if (column && quoted.size < cells.length) {
    boxes.push({
      key: 'guide-column',
      kind: 'guide',
      style: { ...column, top: '0%', height: end(column, 'top', 'height') },
    })
  }
  if (row) boxes.push({ key: 'row', kind: 'row', style: row })
  cells.forEach((cell, index) => {
    const questioned = cell.status === 'questioned'
    if (!questioned && !quoted.has(index)) return
    const style = boxStyle(cell.bbox, width, height, 1.5)
    if (!style) return
    boxes.push({
      key: `cell-${index}`,
      kind: questioned ? 'questioned' : 'cell',
      style,
    })
  })
  return boxes
}

/** A cell's value as the rep reads it, or null when it awaits confirmation. */
export function cellValue(cell) {
  if (!cell || cell.status === 'questioned') return null
  const value = String(cell.value ?? '').trim()
  const unit = String(cell.unit ?? '').trim()
  return unit && value ? `${value} ${unit}` : value
}

/**
 * The original PDF opened at the row's page. Only a same-site file path is
 * linked: the URL comes from our own server, but an href is the one place a
 * `javascript:` string would turn into code, so it is checked anyway.
 */
export function pdfPageUrl(fileUrl, page) {
  const url = String(fileUrl || '')
  if (!/^\/(private\/)?files\//.test(url)) return ''
  const n = Number.parseInt(page, 10)
  return Number.isInteger(n) && n > 0 ? `${url}#page=${n}` : url
}

/** Same check for the page image's src. */
export function safeFileUrl(fileUrl) {
  const url = String(fileUrl || '')
  return /^\/(private\/)?files\//.test(url) ? url : ''
}
