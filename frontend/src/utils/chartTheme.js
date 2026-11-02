import { ref } from 'vue'

/**
 * Vectora's chart palette.
 *
 * frappe-ui charts fall back to ECharts' stock sky/cyan/yellow/salmon, which
 * has no relationship to the indigo system the rest of the app is built from —
 * on the dashboard, the screen an exec actually looks at, that reads as a
 * widget bolted onto someone else's product.
 *
 * ONE series, both themes: these eight are drawn from the brand hues and
 * validated (six-check CVD validator) against BOTH canvases — light #fafbff
 * and dark #131521 — so a series keeps its colour when the user flips the
 * theme, and adjacent series stay separable for the common forms of colour
 * blindness. The one sub-8 adjacent pair (positions 7-8) is legal because
 * every chart carries a legend and direct labels as secondary encoding. The
 * old split ramps failed those checks (light: magenta↔sky ΔE 3.0 deutan and
 * two sub-3:1 series; dark: worst adjacent ΔE 1.8).
 */
const SERIES = [
  '#5b5fe8', // brand indigo — the primary series
  '#0d9488', // teal
  '#d33fd1', // magenta
  '#d97706', // amber
  '#7c3aed', // violet
  '#0284c7', // deep sky
  '#be185d', // deep magenta
  '#4d7c0f', // olive
]

function isDark() {
  if (typeof document === 'undefined') return false
  return document.documentElement.getAttribute('data-theme') === 'dark'
}

export function chartSeriesColors() {
  return [...SERIES]
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
  let value = hex.replace('#', '')
  // #abc is #aabbcc — expand shorthand so a future caller with a 3-digit
  // brand hex gets a color rather than NaN soup.
  if (value.length === 3) {
    value = value.replace(/./g, (c) => c + c)
  }
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
  const palette = [...SERIES]
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

  const darkAxes = dark
    ? {
        yAxis: {
          ...config.yAxis,
          echartOptions: {
            splitLine: {
              lineStyle: { color: 'rgba(255, 255, 255, 0.08)' },
            },
            ...config.yAxis?.echartOptions,
          },
        },
        y2Axis: {
          ...config.y2Axis,
          echartOptions: {
            splitLine: {
              lineStyle: { color: 'rgba(255, 255, 255, 0.08)' },
            },
            ...config.y2Axis?.echartOptions,
          },
        },
      }
    : {}

  // frappe-ui's charts default to CHART_FONT_FAMILY ('InterVar, Inter,
  // sans-serif'), so without this every axis label and legend stays on Inter
  // while the rest of the app is on Plus Jakarta Sans. Same contract as the
  // rest of this module: never override what the caller already set.
  const CHART_FONT =
    "'Plus Jakarta Sans Variable', 'Plus Jakarta Sans', InterVar, sans-serif"
  const out = { ...config, colors: palette, series, ...darkAxes }
  out.textStyle = {
    fontFamily: CHART_FONT,
    ...(config.textStyle ?? {}),
  }

  return out
}

export function withVectoraLux(config) {
  return applyLuxChartTheme(config, isDark())
}

/**
 * The theme as a ref, so a chart config computed from it re-themes the moment
 * the user flips light/dark instead of on the next reload. One observer for
 * the whole app, started on first use; `data-theme` is the attribute
 * frappe-ui's useColorScheme writes.
 */
const darkRef = ref(isDark())
let observing = false

export function useIsDark() {
  if (
    !observing &&
    typeof document !== 'undefined' &&
    typeof MutationObserver !== 'undefined'
  ) {
    observing = true
    new MutationObserver(() => {
      darkRef.value = isDark()
    }).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
  }
  darkRef.value = isDark()
  return darkRef
}
