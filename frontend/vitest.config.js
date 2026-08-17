import { defineConfig } from 'vitest/config'
import path from 'path'

export default defineConfig({
  test: {
    globals: true,
    environment: 'happy-dom',
    root: import.meta.dirname,
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.test.js', 'src/**/*.test.js'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'json-summary'],
      reportsDirectory: './coverage',
      // The whole pure-logic layer, not a hand-picked list. Naming ten files
      // meant a PR adding an untested util contributed zero lines to the
      // report, so codecov's 85% patch target passed trivially -- a gate that
      // cannot fail. Components are still excluded because there are no
      // component tests yet; that is tracked separately rather than hidden by
      // pretending the covered set is the whole app.
      include: ['src/utils/**/*.{js,ts}', 'src/composables/**/*.{js,ts}'],
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
    },
  },
})
