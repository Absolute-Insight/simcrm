import frappeUIPreset from 'frappe-ui/tailwind'

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
      colors: {
        // Vectora brand palette — sampled from the logo mark.
        // `brand` is the indigo primary; sky/magenta are the gradient endpoints
        // and are reserved for accents, never for text on light surfaces.
        brand: {
          DEFAULT: '#5B5FE8',
          sky: '#21ABFB',
          magenta: '#DF5FEB',
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
      backgroundImage: {
        'brand-gradient':
          'linear-gradient(100deg, #21ABFB 0%, #5B5FE8 55%, #DF5FEB 100%)',
      },
    },
  },
  plugins: [],
}
