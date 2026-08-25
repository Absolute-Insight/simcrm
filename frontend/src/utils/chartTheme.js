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

/**
 * Vectora Lux — the dashboard's glow treatment, expressed purely as config.
 *
 * frappe-ui's charts merge each series' `echartOptions` into the final ECharts
 * series (caller-last), which is the whole mechanism here: the glow, gradients,
 * and fades below are plain data injected through that seam. Dark mode gets a
 * same-hue glow under lines and gradient fills; light mode gets the gradient
 * fills only. A config that chose its own colors is left entirely alone, same
 * contract as withVectoraTheme.
 */
const LINE_GLOW = { blur: 14, alpha: 0.4, offsetY: 6 }

export function hexToRgba(hex, alpha) {
  const value = hex.replace('#', '')
  const r = parseInt(value.slice(0, 2), 16)
  const g = parseInt(value.slice(2, 4), 16)
  const b = parseInt(value.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function verticalFade(hex, topAlpha, bottomAlpha) {
  return {
    type: 'linear',
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: hexToRgba(hex, topAlpha) },
      { offset: 1, color: hexToRgba(hex, bottomAlpha) },
    ],
  }
}

export function applyLuxChartTheme(config, dark) {
  if (!config || typeof config !== 'object') return config
  if (config.colors?.length) return config
  const palette = dark ? [...DARK_SERIES] : [...LIGHT_SERIES]
  if (!Array.isArray(config.series)) return { ...config, colors: palette }

  const series = config.series.map((s, index) => {
    const hue = s.color || palette[index % palette.length]
    const lux = {}
    if (s.type === 'bar') {
      lux.itemStyle = { color: verticalFade(hue, 1, dark ? 0.5 : 0.7) }
    }
    if (s.type === 'line' || s.type === 'area') {
      if (dark) {
        lux.lineStyle = {
          shadowBlur: LINE_GLOW.blur,
          shadowColor: hexToRgba(hue, LINE_GLOW.alpha),
          shadowOffsetY: LINE_GLOW.offsetY,
        }
      }
      lux.areaStyle = {
        color: verticalFade(hue, dark ? 0.32 : 0.22, 0),
        opacity: 1,
      }
    }
    if (!Object.keys(lux).length) return s
    return { ...s, echartOptions: { ...lux, ...s.echartOptions } }
  })

  return { ...config, colors: palette, series }
}

export function withVectoraLux(config) {
  return applyLuxChartTheme(config, isDark())
}
