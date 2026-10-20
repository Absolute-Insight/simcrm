// Dark-theme stand-ins for the colours an email sets on itself. The frame's
// stylesheet themes the prose, but inline `color:`, `<font color>` and
// `bgcolor` belong to the sender and win over it, so on the dark theme an
// Outlook body's `color:black` sat on the dark canvas unreadable.
//
// Ported from upstream frappe/crm #2989, with two changes: the surface is our
// email canvas rather than frappe-ui's gray, and the text floor is WCAG AA
// (4.5:1) rather than 3:1, because email body text is normal-size text; borders
// keep the 3:1 non-text floor.
//
// This is our code now. Upstream deleted it a day after merging (#2995), when
// its email rendering moved to `EmailItem` in frappe's unpublished UI library;
// we keep our own EmailContent.vue, so a later port will see upstream
// "deleting" this file and should not follow it.

const WHITE = { r: 255, g: 255, b: 255, a: 1 }
const BLACK = { r: 0, g: 0, b: 0, a: 1 }
// The dark `--email-canvas` in Activities/emailContent.css (#1c1e2c); a unit
// test keeps the two in step.
export const DARK_SURFACE = { r: 28, g: 30, b: 44, a: 1 }

export const MIN_TEXT_CONTRAST = 4.5
export const MIN_NON_TEXT_CONTRAST = 3
const LIGHT_BACKGROUND = 0.4
const DARKENED_BACKGROUND = 0.1

export function parseRgb(value) {
  const match = value?.match(
    /^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/,
  )
  if (!match) return null
  const [, r, g, b, a = '1'] = match
  return { r: +r, g: +g, b: +b, a: +a }
}

export function toCss({ r, g, b, a }) {
  const channels = [r, g, b].map(Math.round).join(', ')
  return a < 1 ? `rgba(${channels}, ${a})` : `rgb(${channels})`
}

export function luminance({ r, g, b }) {
  const linear = (channel) => {
    const c = channel / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
}

export function contrast(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

export function blend(top, bottom) {
  const mix = (channel) => top[channel] * top.a + bottom[channel] * (1 - top.a)
  return { r: mix('r'), g: mix('g'), b: mix('b'), a: 1 }
}

// Shifting every channel by the same amount keeps hue and saturation, and this
// shift moves the lightness from L to 1 - L: black turns white, navy turns light blue.
export function invertLightness({ r, g, b, a }) {
  const shift = 255 - Math.max(r, g, b) - Math.min(r, g, b)
  return { r: r + shift, g: g + shift, b: b + shift, a }
}

function mixUntil(color, target, isGoodEnough) {
  for (let step = 0; step <= 10; step++) {
    const amount = step / 10
    const mixed = { ...color }
    for (const channel of ['r', 'g', 'b']) {
      mixed[channel] =
        color[channel] + (target[channel] - color[channel]) * amount
    }
    if (isGoodEnough(mixed)) return mixed
  }
  return { ...target, a: color.a }
}

export function darkModeBackground(background) {
  if (background.a === 0) return null
  if (luminance(background) <= LIGHT_BACKGROUND) return null
  return mixUntil(
    invertLightness(background),
    BLACK,
    (c) => luminance(c) <= DARKENED_BACKGROUND,
  )
}

export function darkModeText(
  color,
  background = DARK_SURFACE,
  floor = MIN_TEXT_CONTRAST,
) {
  if (color.a === 0) return null
  const before = contrast(color, background)
  if (before >= floor) return null
  const lighter = mixUntil(
    invertLightness(color),
    WHITE,
    (c) => contrast(c, background) >= floor,
  )
  return contrast(lighter, background) > before ? lighter : null
}

const BORDER_SIDES = ['top', 'right', 'bottom', 'left']

// Run while the frame is still light, so computed colours are the email's own.
// Inherited text is checked too wherever the background changes, because black
// prose on a white table cell turns unreadable once that cell goes dark.
export function collectDarkModeColors(emailContent) {
  const overrides = []
  const view = emailContent.ownerDocument.defaultView
  const darkBackgrounds = new Map([[emailContent, DARK_SURFACE]])

  function backgroundInDarkMode(el) {
    if (!darkBackgrounds.has(el)) {
      const own = parseRgb(view.getComputedStyle(el).backgroundColor)
      const behind = backgroundInDarkMode(el.parentElement)
      const visible = own?.a > 0 ? darkModeBackground(own) ?? own : null
      darkBackgrounds.set(el, visible ? blend(visible, behind) : behind)
    }
    return darkBackgrounds.get(el)
  }

  function add(el, property, darkColor) {
    overrides.push({
      el,
      property,
      darkColor: toCss(darkColor),
      original: {
        value: el.style.getPropertyValue(property),
        priority: el.style.getPropertyPriority(property),
      },
    })
  }

  for (const el of emailContent.querySelectorAll(
    '[style], font[color], [bgcolor]',
  )) {
    const computed = view.getComputedStyle(el)
    const background = backgroundInDarkMode(el)
    let backgroundChanged = false

    if (el.style.backgroundColor || el.getAttribute('bgcolor')) {
      const original = parseRgb(computed.backgroundColor)
      const dark = original && darkModeBackground(original)
      if (dark) {
        add(el, 'background-color', dark)
        backgroundChanged = true
      }
    }

    if (el.style.color || el.getAttribute('color') || backgroundChanged) {
      const original = parseRgb(computed.color)
      const dark = original && darkModeText(original, background)
      if (dark) add(el, 'color', dark)
    }

    for (const side of BORDER_SIDES) {
      if (!el.style.getPropertyValue(`border-${side}-style`)) continue
      const original = parseRgb(
        computed.getPropertyValue(`border-${side}-color`),
      )
      const dark =
        original && darkModeText(original, background, MIN_NON_TEXT_CONTRAST)
      if (dark) add(el, `border-${side}-color`, dark)
    }
  }
  return overrides
}

// Swap the overrides in for the dark theme and put the sender's own values
// back for the light one, so toggling the theme is lossless in both directions.
export function applyDarkModeColors(overrides, dark) {
  for (const { el, property, original, darkColor } of overrides) {
    if (dark) el.style.setProperty(property, darkColor, 'important')
    else if (original.value)
      el.style.setProperty(property, original.value, original.priority)
    else el.style.removeProperty(property)
  }
}
