import frappeUIPresetModule from 'frappe-ui/tailwind'

// beta.53 moved the preset behind a re-export hop (tailwind/index.js ->
// preset.js); under jiti's CJS interop that arrives double-wrapped, and a
// wrapped preset is silently ignored by tailwind v3 -- plugins and all.
const frappeUIPreset = frappeUIPresetModule.default ?? frappeUIPresetModule

export default {
  presets: [frappeUIPreset],
  content: [{ raw: '<div class="prose-f"></div>', extension: 'html' }],
  theme: {
    extend: {},
  },
  plugins: [],
}
