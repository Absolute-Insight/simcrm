/**
 * Ring math for RadialGauge, kept pure so the arc a gauge draws is testable
 * without mounting SVG. The number shown on the gauge is the server's value
 * as-is; only the drawn arc clamps to the ring's 0-100 domain.
 */
export function ringDash(value, radius) {
  // Non-finite input (null, text, an unguarded x/0 ratio) draws an empty
  // ring rather than a full one: an absent value must not read as 100%.
  const number = Number(value)
  const pct = Number.isFinite(number) ? Math.min(100, Math.max(0, number)) : 0
  const circumference = 2 * Math.PI * radius
  const filled = (circumference * pct) / 100
  return { pct, dasharray: `${filled} ${circumference - filled}` }
}

/**
 * Same display rules as StatTile's delta (see StatTile.vue): one decimal
 * under 100, integers to 999, a comparison past that — sixteen significant
 * figures of period-over-period change is noise. Zero and absent deltas
 * render as nothing rather than "+0".
 */
export function formatDelta(delta, suffix = '') {
  const value = Number(delta) || 0
  if (!value) return ''
  const sign = value > 0 ? '+' : '−'
  const magnitude = Math.abs(value)
  if (magnitude >= 1000) return `${value > 0 ? '>' : '<−'}999${suffix}`
  const rounded =
    magnitude >= 100 ? Math.round(magnitude) : Math.round(magnitude * 10) / 10
  if (!rounded) return ''
  return `${sign}${rounded}${suffix}`
}
