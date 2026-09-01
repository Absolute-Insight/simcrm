import { describe, expect, it } from 'vitest'
import {
  applyLuxChartTheme,
  hexToRgba,
  useIsDark,
  withVectoraTheme,
} from '@/utils/chartTheme'

function axisConfig(overrides = {}) {
  return {
    data: [],
    title: 'Revenue',
    xAxis: { key: 'month', type: 'category' },
    yAxis: {},
    series: [
      { name: 'won', type: 'line' },
      { name: 'lost', type: 'bar' },
      { name: 'pipeline', type: 'area' },
    ],
    ...overrides,
  }
}

describe('hexToRgba', () => {
  it('converts a hex color and alpha to an rgba() string', () => {
    expect(hexToRgba('#5b5fe8', 0.5)).toBe('rgba(91, 95, 232, 0.5)')
  })

  it('handles full alpha', () => {
    expect(hexToRgba('#000000', 1)).toBe('rgba(0, 0, 0, 1)')
  })

  it('expands 3-digit shorthand hex', () => {
    expect(hexToRgba('#abc', 1)).toBe('rgba(170, 187, 204, 1)')
  })
})

describe('applyLuxChartTheme', () => {
  it('passes through nullish and non-object configs', () => {
    expect(applyLuxChartTheme(null, true)).toBe(null)
    expect(applyLuxChartTheme(undefined, false)).toBe(undefined)
  })

  it('never overrides a config that set its own colors', () => {
    const config = axisConfig({ colors: ['#123456'] })
    expect(applyLuxChartTheme(config, true)).toBe(config)
  })

  it('applies one brand series to both themes so colors follow the entity', () => {
    const config = { title: 'Sources', data: [] }
    const dark = applyLuxChartTheme(config, true)
    const light = applyLuxChartTheme(config, false)
    expect(dark.colors).toHaveLength(8)
    expect(light.colors).toEqual(dark.colors)
  })

  it('anchors the palette on the validated brand set', () => {
    const dark = applyLuxChartTheme({ title: 'x', data: [] }, true)
    expect(dark.colors.slice(0, 4)).toEqual([
      '#5b5fe8',
      '#0d9488',
      '#d33fd1',
      '#d97706',
    ])
  })

  it('gives line series a same-hue glow in dark mode only', () => {
    const dark = applyLuxChartTheme(axisConfig(), true)
    const light = applyLuxChartTheme(axisConfig(), false)
    const darkLine = dark.series[0].echartOptions.lineStyle
    expect(darkLine.shadowBlur).toBe(14)
    expect(darkLine.shadowColor).toMatch(/^rgba\(/)
    expect(light.series[0].echartOptions?.lineStyle).toBeUndefined()
  })

  it('derives the glow from the series own color when one is set', () => {
    const config = axisConfig({
      series: [{ name: 'won', type: 'line', color: '#ff0000' }],
    })
    const themed = applyLuxChartTheme(config, true)
    expect(themed.series[0].echartOptions.lineStyle.shadowColor).toBe(
      'rgba(255, 0, 0, 0.4)',
    )
  })

  it('gives bar series a vertical gradient fill in both modes', () => {
    for (const dark of [true, false]) {
      const themed = applyLuxChartTheme(axisConfig(), dark)
      const fill = themed.series[1].echartOptions.itemStyle.color
      expect(fill.type).toBe('linear')
      expect(fill.colorStops).toHaveLength(2)
      expect(fill.colorStops[0].color).toMatch(/^rgba\(/)
    }
  })

  it('gives line and area series a gradient area fill fading to transparent', () => {
    const themed = applyLuxChartTheme(axisConfig(), false)
    for (const idx of [0, 2]) {
      const fill = themed.series[idx].echartOptions.areaStyle.color
      expect(fill.type).toBe('linear')
      expect(fill.colorStops[1].color).toMatch(/, 0\)$/)
    }
  })

  it('lets a caller-supplied echartOptions key win over the lux one', () => {
    const lineStyle = { width: 4 }
    const config = axisConfig({
      series: [{ name: 'won', type: 'line', echartOptions: { lineStyle } }],
    })
    const themed = applyLuxChartTheme(config, true)
    expect(themed.series[0].echartOptions.lineStyle).toBe(lineStyle)
  })

  it('does not mutate the input config', () => {
    const config = axisConfig()
    const snapshot = JSON.stringify(config)
    applyLuxChartTheme(config, true)
    expect(JSON.stringify(config)).toBe(snapshot)
  })

  it('fades y-axis split lines in dark mode without clobbering caller axis options', () => {
    const dark = applyLuxChartTheme(axisConfig(), true)
    expect(dark.yAxis.echartOptions.splitLine.lineStyle.color).toBe(
      'rgba(255, 255, 255, 0.08)',
    )
    expect(dark.y2Axis.echartOptions.splitLine.lineStyle.color).toBe(
      'rgba(255, 255, 255, 0.08)',
    )
    expect(
      applyLuxChartTheme(axisConfig(), false).yAxis.echartOptions,
    ).toBeUndefined()
  })
})

describe('withVectoraTheme (existing contract)', () => {
  it('still applies the palette without touching explicit colors', () => {
    expect(withVectoraTheme({ colors: ['#abc'] }).colors).toEqual(['#abc'])
    expect(withVectoraTheme({}).colors).toHaveLength(8)
  })
})

describe('chart typography', () => {
  it('sets the app font family on the chart text style', () => {
    const out = applyLuxChartTheme(axisConfig(), false)
    expect(out.textStyle.fontFamily).toMatch(/Plus Jakarta Sans/)
  })

  it('does not override a font family the caller already chose', () => {
    const config = axisConfig({ textStyle: { fontFamily: 'Courier New' } })
    const out = applyLuxChartTheme(config, false)
    expect(out.textStyle.fontFamily).toBe('Courier New')
  })
})

describe('useIsDark', () => {
  it('tracks the data-theme attribute without a reload', async () => {
    document.documentElement.setAttribute('data-theme', 'light')
    const dark = useIsDark()
    expect(dark.value).toBe(false)
    document.documentElement.setAttribute('data-theme', 'dark')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(dark.value).toBe(true)
    document.documentElement.setAttribute('data-theme', 'light')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(dark.value).toBe(false)
  })
})
