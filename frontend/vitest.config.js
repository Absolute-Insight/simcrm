import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import appConfig from './vite.config.js'

// Component tests resolve imports exactly as the app does: the frappe-ui
// compat shim, its subpath entries and the @framework/ui stub all come from
// vite.config.js rather than a copy that would drift from it.
export default defineConfig(async (env) => {
  // Tests never see the bench's @framework/ui: the no-op stub keeps a run on
  // a bare checkout (CI, a worktree) identical to one inside the devcontainer.
  process.env.FRAMEWORK_UI_STUB = '1'
  const app = await appConfig({ ...env, mode: 'test' })
  return {
    plugins: [vue()],
    // A worktree symlinks frontend/node_modules from the main checkout, which
    // puts every package outside vite's fs allow-list ("Denied ID ...?raw").
    // Nothing is served to a browser here, so the restriction protects nothing.
    server: { fs: { strict: false } },
    test: {
      globals: true,
      environment: 'happy-dom',
      root: import.meta.dirname,
      setupFiles: ['./tests/setup.js'],
      include: ['tests/**/*.test.js', 'src/**/*.test.js'],
      // frappe-ui and the icon set ship .vue/.ts sources; vitest must
      // transform them rather than hand them to node as externals.
      server: { deps: { inline: [/frappe-ui/, /@phosphor-icons/] } },
      coverage: {
        provider: 'v8',
        reporter: ['text', 'lcov', 'json-summary'],
        reportsDirectory: './coverage',
        // The whole pure-logic layer, not a hand-picked list. Naming ten files
        // meant a PR adding an untested util contributed zero lines to the
        // report, so codecov's 85% patch target passed trivially -- a gate that
        // cannot fail. Component tests mount SFCs under tests/component/; the
        // components themselves are left out of the target until enough of
        // them are covered for a patch percentage to mean something.
        include: ['src/utils/**/*.{js,ts}', 'src/composables/**/*.{js,ts}'],
      },
    },
    resolve: { alias: app.resolve.alias, dedupe: app.resolve.dedupe },
  }
})
