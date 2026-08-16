// frappe-ui's tailwind preset, adapted for the tailwind-4 compat layer.
//
// The library still develops on tailwind 3.4 (its devDependency), and two of
// its habits are rejected by v4's config-compat:
//
//   1. `addComponents` entries whose selectors are not single class names
//      (`[data-theme='dark'] [type='checkbox']:checked`, `:focus-visible`) —
//      v4 enforces class-only selectors there. Those entries belong in the
//      base layer, so they are rerouted to `addBase`, which imposes no such
//      rule and emits at the same layer the preflight rules live in.
//   2. `@apply placeholder-ink-gray-4` — the `placeholder-*` color utilities
//      were removed in v4; the modern spelling is `placeholder:text-*`.
//
// Everything else in the preset (theme, matchUtilities, the token variables)
// passes through untouched. Delete this wrapper when frappe-ui ships a
// tailwind-4 preset.
import frappeUIPresetModule from 'frappe-ui/tailwind'

const frappeUIPreset = frappeUIPresetModule.default ?? frappeUIPresetModule

const SINGLE_CLASS = /^\.[A-Za-z][\w-]*$/

function fixApplyStrings(value) {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object') return value
  const out = {}
  for (const [k, v] of Object.entries(value)) {
    const key = k.includes('@apply')
      ? k.replace(/placeholder-(ink-[\w-]+|gray-\d+)/g, 'placeholder:text-$1')
      : k
    out[key] = fixApplyStrings(v)
  }
  return out
}

function wrapPlugin(pluginEntry) {
  // `plugin.withOptions` exports (forms, typography) are option factories, not
  // handlers — invoke them with defaults to get the real {handler, config}.
  const resolved =
    typeof pluginEntry === 'function' && pluginEntry.__isOptionsFunction
      ? pluginEntry()
      : pluginEntry
  const original =
    typeof resolved === 'function' ? { handler: resolved } : resolved
  const handler = (api) => {
    const safeAddComponents = (styles, options) => {
      for (const group of Array.isArray(styles) ? styles : [styles]) {
        const classy = {}
        const bare = {}
        for (const [selector, value] of Object.entries(group)) {
          const fixed = fixApplyStrings(value)
          const classOnly = selector
            .split(',')
            .every((s) => SINGLE_CLASS.test(s.trim()))
          if (classOnly) classy[selector] = fixed
          else bare[selector] = fixed
        }
        if (Object.keys(classy).length) api.addComponents(classy, options)
        if (Object.keys(bare).length) api.addBase(bare)
      }
    }
    return original.handler({ ...api, addComponents: safeAddComponents })
  }
  return original.config ? { handler, config: original.config } : handler
}

export default {
  ...frappeUIPreset,
  plugins: (frappeUIPreset.plugins || []).map(wrapPlugin),
}
