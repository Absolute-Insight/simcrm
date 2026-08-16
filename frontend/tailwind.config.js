// the v4-compat adapter owns the interop unwrapping and the v3-habit fixes
import frappeUIPreset from './tailwind.preset-v4.js'

export default {
  presets: [frappeUIPreset],
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
    './node_modules/frappe-ui/src/**/*.{vue,js,ts,jsx,tsx}',
    '../node_modules/frappe-ui/src/**/*.{vue,js,ts,jsx,tsx}',
    './node_modules/frappe-ui/frappe/**/*.{vue,js,ts,jsx,tsx}',
    '../node_modules/frappe-ui/frappe/**/*.{vue,js,ts,jsx,tsx}',
    // linked @framework/ui source (apps/frappe/ui/src) — scan so its utility and
    // arbitrary-variant classes (e.g. Notifications TabButtons overrides) are generated
    '../../frappe/ui/src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  safelist: [
    '!text-gray-700',
    '!text-blue-600',
    '!text-green-700',
    '!text-red-600',
    '!text-pink-600',
    '!text-orange-600',
    '!text-amber-600',
    '!text-yellow-600',
    '!text-cyan-600',
    '!text-teal-600',
    '!text-violet-600',
    '!text-purple-600',
    '!text-ink-gray-9',
  ],
  theme: {
    extend: {
      fontFamily: {
        // Display face for the wordmark, panel headings and dashboard numerals.
        // Body text stays on frappe-ui's Inter.
        display: [
          'Space Grotesk Variable',
          'InterVar',
          'ui-sans-serif',
          'system-ui',
          'sans-serif',
        ],
      },
      colors: {
        // Vectora brand palette — sampled from the logo mark. This is the
        // utility-class face of the brand; the CSS-variable face lives in
        // scripts/generate_vectora_theme.py (BRAND) and the two share the
        // same hexes. Kept as literals rather than `var(--brand-*)` so the
        // Tailwind opacity modifiers (`text-brand-500/60`) keep working.
        //
        // The gradient endpoints (sky, magenta) are deliberately NOT here:
        // they exist only to compose --brand-gradient, and a `text-brand-sky`
        // utility would be advertising a colour the design language does not
        // let you spend.
        brand: {
          // `text-brand` / `bg-brand` is the brand used as ink, so it has to
          // flip with the theme: 500 is 4.9:1 on the light canvas but 3.3:1 on
          // the dark one. The numbered steps below stay literal.
          DEFAULT: 'var(--brand-ink)',
          50: '#EFF0FD',
          100: '#E0E2FB',
          200: '#C5C8F7',
          300: '#A5A8F2',
          400: '#8084ED',
          500: '#5B5FE8',
          600: '#4A4BD1',
          700: '#3C3CAF',
          800: '#30308C',
          900: '#282870',
        },
      },
    },
  },
  plugins: [],
}
