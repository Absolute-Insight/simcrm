import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import fs from 'node:fs'
import path from 'path'
import { VitePWA } from 'vite-plugin-pwa'

// https://vitejs.dev/config/
export default defineConfig(async ({ mode }) => {
  const isDev = mode === 'development'
  const config = {
    plugins: [
      vue(),
      vueJsx(),
      VitePWA({
        registerType: 'autoUpdate',
        workbox: {
          maximumFileSizeToCacheInBytes: 8 * 1024 * 1024,
        },
        devOptions: {
          enabled: true,
        },
        manifest: {
          display: 'standalone',
          name: 'Vectora',
          short_name: 'Vectora',
          start_url: '/crm',
          description: 'Vectora — proactive, open-source CRM',
          theme_color: '#5B5FE8',
          background_color: '#ffffff',
          icons: [
            {
              src: '/assets/crm/manifest/manifest-icon-192.maskable.png',
              sizes: '192x192',
              type: 'image/png',
              purpose: 'any',
            },
            {
              src: '/assets/crm/manifest/manifest-icon-192.maskable.png',
              sizes: '192x192',
              type: 'image/png',
              purpose: 'maskable',
            },
            {
              src: '/assets/crm/manifest/manifest-icon-512.maskable.png',
              sizes: '512x512',
              type: 'image/png',
              purpose: 'any',
            },
            {
              src: '/assets/crm/manifest/manifest-icon-512.maskable.png',
              sizes: '512x512',
              type: 'image/png',
              purpose: 'maskable',
            },
          ],
        },
      }),
    ],
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, 'src'),
        // ---- frappe-ui compat layer -------------------------------------
        // @framework/ui still imports FeatherIcon from 'frappe-ui'; beta.53
        // removed it (ADR-0008). The bare specifier resolves to a shim that
        // re-exports the real package plus a sprite-backed FeatherIcon; the
        // real package is reachable as 'frappe-ui-actual'. Subpath entries
        // must precede the bare key — a string alias matches by prefix, so
        // without them 'frappe-ui/experimental' would rewrite under the shim
        // directory. getAliases() overrides all of these to the local
        // checkout for dev.
        'frappe-ui/experimental': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/experimental.ts',
        ),
        'frappe-ui/editor-style.css': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/src/molecules/editor/style.css',
        ),
        'frappe-ui/editor': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/src/molecules/editor/index.ts',
        ),
        'frappe-ui/list': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/src/molecules/list/index.ts',
        ),
        'frappe-ui/charts': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/src/charts/index.ts',
        ),
        'frappe-ui/icons': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/icons/index.ts',
        ),
        'frappe-ui/internals': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/internals.ts',
        ),
        // tailwind-4 compat: frappe-ui's stylesheet still uses v3 directives
        'frappe-ui/style.css': path.resolve(
          import.meta.dirname,
          'src/lib/frappe-ui-compat/style.css',
        ),
        'frappe-ui-fonts-inter.css': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/src/fonts/Inter/inter.css',
        ),
        'frappe-ui/tailwind': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/tailwind/index.js',
        ),
        'frappe-ui-actual': path.resolve(
          import.meta.dirname,
          'node_modules/frappe-ui/src/index.ts',
        ),
        'frappe-ui': path.resolve(
          import.meta.dirname,
          'src/lib/frappe-ui-compat/index.ts',
        ),
        // -----------------------------------------------------------------
        // point at the package src dir (not index.ts) so subpath imports like
        // `@framework/ui/components/Onboarding` resolve. Importing subpaths avoids the
        // barrel, which `export *`s components (Grid/Phone/FormLayout) beyond
        // what this app uses.
        //
        // @framework/ui is unpublished; the real package only exists inside a
        // bench (dev, frappe_docker builds). A bare checkout — CI's Production
        // Build — gets the in-repo no-op stub instead, and FRAMEWORK_UI_STUB=1
        // forces the stub so that bare path can be tested from a dev bench.
        // See src/lib/framework-ui-stub/README.md.
        '@framework/ui': resolveFrameworkUi(),
      },
      // ensure the linked framework package reuses the host app's single copy of each peer.
      // `dompurify` is an implicit dep of @framework/ui's sanitize util (not declared in its
      // package.json); dedupe resolves it to the host's copy since the symlinked source has
      // no node_modules of its own.
      // the editor packages must resolve to one copy each: tiptap imports
      // `@tiptap/pm/model` while prosemirror-state/transform/tables import bare
      // `prosemirror-model`, so a nested install of either throws "multiple
      // versions of prosemirror-model were loaded" on mention insert. Unlike
      // optimizeDeps (dev-only) this also applies to the production build.
      dedupe: [
        'vue',
        'vue-router',
        'frappe-ui',
        'dompurify',
        '@tiptap/core',
        '@tiptap/pm',
        '@tiptap/vue-3',
        'prosemirror-model',
        'prosemirror-state',
        'prosemirror-view',
        'prosemirror-transform',
      ],
    },
    optimizeDeps: {
      include: [
        'feather-icons',
        'tailwind.config.js',
        'prosemirror-state',
        'prosemirror-view',
        'lowlight',
        'interactjs',
      ],
    },
    server: {
      fs: {
        // allow the bench `apps/` dir so Vite can serve linked local packages
        // (frappe-ui, @framework/ui) that live in sibling app repos
        allow: [path.resolve(import.meta.dirname, '../..')],
      },
    },
  }

  const frappeui = await importFrappeUIPlugin(isDev, config)
  config.plugins.unshift(
    frappeui({
      frappeProxy: true,
      lucideIcons: true,
      jinjaBootData: true,
      buildConfig: {
        indexHtmlPath: '../crm/www/crm.html',
        emptyOutDir: true,
        sourcemap: true,
      },
    }),
  )

  return config
})

function resolveFrameworkUi() {
  // two layouts carry the real package: building through the bench symlink
  // (frappe-bench/apps/crm/frontend) and building from the working tree with
  // the bench checked out beside it
  const candidates = [
    path.resolve(import.meta.dirname, '../../frappe/ui/src'),
    path.resolve(import.meta.dirname, '../frappe-bench/apps/frappe/ui/src'),
  ]
  const stub = path.resolve(import.meta.dirname, 'src/lib/framework-ui-stub')
  if (process.env.FRAMEWORK_UI_STUB === '1') {
    console.info('@framework/ui: stub forced via FRAMEWORK_UI_STUB=1')
    return stub
  }
  const real = candidates.find((p) => fs.existsSync(p))
  if (real) return real
  console.warn('@framework/ui: no bench sibling found, building with the stub')
  return stub
}

async function importFrappeUIPlugin(isDev, config) {
  if (isDev) {
    try {
      // Check if local frappe-ui has the vite plugin file
      const fs = await import('node:fs')
      const localVitePluginPath = path.resolve(
        import.meta.dirname,
        '../frappe-ui/vite/index.js',
      )

      if (fs.existsSync(localVitePluginPath)) {
        const module = await import('../frappe-ui/vite/index.js')
        console.info('Local frappe-ui vite plugin found, using local plugin')
        config.resolve.alias = getAliases(config)
        return module.default
      } else {
        console.warn('Local frappe-ui vite plugin not found, using npm package')
      }
    } catch (error) {
      console.warn(
        'Local frappe-ui not found, falling back to npm package:',
        error.message,
      )
    }
  }
  // Fall back to npm package if local import fails
  const module = await import('frappe-ui/vite')
  return module.default
}

function getAliases(config) {
  return {
    ...config.resolve.alias,
    // dev: point every frappe-ui path at the local checkout. Subpath entries
    // must precede the bare key (string aliases match by prefix), and the
    // bare 'frappe-ui' stays on the compat shim — only 'frappe-ui-actual'
    // moves to the local checkout, so the FeatherIcon bridge for
    // @framework/ui works identically in dev and prod.
    'frappe-ui/tailwind': path.resolve(
      import.meta.dirname,
      '../frappe-ui/tailwind/index.js',
    ),
    'frappe-ui/style.css': path.resolve(
      import.meta.dirname,
      'src/lib/frappe-ui-compat/style.css',
    ),
    'frappe-ui-fonts-inter.css': path.resolve(
      import.meta.dirname,
      '../frappe-ui/src/fonts/Inter/inter.css',
    ),
    'frappe-ui/experimental': path.resolve(
      import.meta.dirname,
      '../frappe-ui/experimental.ts',
    ),
    'frappe-ui/icons': path.resolve(
      import.meta.dirname,
      '../frappe-ui/icons/index.ts',
    ),
    'frappe-ui/editor-style.css': path.resolve(
      import.meta.dirname,
      '../frappe-ui/src/molecules/editor/style.css',
    ),
    'frappe-ui/editor': path.resolve(
      import.meta.dirname,
      '../frappe-ui/src/molecules/editor/index.ts',
    ),
    'frappe-ui/list': path.resolve(
      import.meta.dirname,
      '../frappe-ui/src/molecules/list/index.ts',
    ),
    'frappe-ui/charts': path.resolve(
      import.meta.dirname,
      '../frappe-ui/src/charts/index.ts',
    ),
    'frappe-ui/internals': path.resolve(
      import.meta.dirname,
      '../frappe-ui/internals.ts',
    ),
    'frappe-ui-actual': path.resolve(
      import.meta.dirname,
      '../frappe-ui/src/index.ts',
    ),
    'frappe-ui': path.resolve(
      import.meta.dirname,
      'src/lib/frappe-ui-compat/index.ts',
    ),
  }
}
