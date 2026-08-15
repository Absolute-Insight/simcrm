/**
 * Vectora's chart palette.
 *
 * frappe-ui charts fall back to ECharts' stock sky/cyan/yellow/salmon, which
 * has no relationship to the indigo system the rest of the app is built from —
 * on the dashboard, the screen an exec actually looks at, that reads as a
 * widget bolted onto someone else's product. These series colours are drawn
 * from the brand gradient's own stops and spaced by hue so adjacent series stay
 * separable, including for the common forms of colour blindness (no red/green
 * pair carries meaning on its own).
 *
 * Two ramps because a chart is drawn on the canvas: the light one is saturated
 * enough to hold against near-white, the dark one lifted so it does not sink
 * into #131521.
 */

// sky and magenta are the gradient's own ends, indigo its middle; the rest are
// spaced around the wheel from there, avoiding the 90-150 deg band that reads
// as "good" next to a red that reads as "bad".
const LIGHT_SERIES = [
  '#5b5fe8', // brand indigo — the primary series
  '#21abfb', // gradient sky
  '#df5feb', // gradient magenta
  '#0d9488', // teal
  '#d97706', // amber
  '#7c3aed', // violet
  '#0369a1', // deep sky
  '#be185d', // deep magenta
]

const DARK_SERIES = [
  '#a5a8f2',
  '#7dc9fd',
  '#eb9bf3',
  '#2dd4bf',
  '#fbbf24',
  '#a78bfa',
  '#38bdf8',
  '#f472b6',
]

function isDark() {
  if (typeof document === 'undefined') return false
  return document.documentElement.getAttribute('data-theme') === 'dark'
}

export function chartSeriesColors() {
  return isDark() ? [...DARK_SERIES] : [...LIGHT_SERIES]
}

/**
 * Return `config` with Vectora's palette applied, without overriding a config
 * that asked for specific colours itself.
 */
export function withVectoraTheme(config) {
  if (!config || typeof config !== 'object') return config
  if (config.colors?.length) return config
  return { ...config, colors: chartSeriesColors() }
}
