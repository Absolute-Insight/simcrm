import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import fs from 'node:fs'
import path from 'path'
import { VitePWA } from 'vite-plugin-pwa'

/**
 * Ship the fonts the built CSS actually asks for.
 *
 * Tailwind 4's postcss plugin resolves `@import` itself, so vite never sees
 * `@fontsource-variable/plus-jakarta-sans` or frappe-ui's inter.css as modules --
 * it neither rewrites their `url()`s nor emits the woff2 they point at. The
 * built CSS keeps the source-relative paths (`./files/…woff2`,
 * `Inter.var.woff2?v=3.19`) and every one of them 404s. Both brand typefaces
 * fall back to `-apple-system`, in production only: the dev server serves them
 * straight out of node_modules, so nothing looks wrong until the image is
 * built. Under Tailwind 3 vite handled those imports and this did not arise.
 *
 * The copy list is read back out of the emitted CSS rather than written here,
 * so adding a subset or bumping frappe-ui cannot silently drop a file again.
 * Anything it cannot resolve fails the build, because a font that 404s is not
 * worth discovering from a screenshot.
 */
function shipFontsReferencedByCss({ searchRoots }) {
  return {
    name: 'ship-fonts-referenced-by-css',
    apply: 'build',
    writeBundle(options, bundle) {
      const outDir = options.dir
      const wanted = new Map()

      for (const [fileName, chunk] of Object.entries(bundle)) {
        if (!fileName.endsWith('.css') || chunk.type !== 'asset') continue
        const css = String(chunk.source)
        for (const match of css.matchAll(
          /url\(\s*['"]?([^'")?]+\.woff2?)(?:\?[^'")]*)?['"]?\s*\)/g,
        )) {
          const ref = match[1]
          if (/^(https?:)?\/\//.test(ref) || ref.startsWith('data:')) continue
          // Resolve relative to the CSS file, which is where the browser will.
          const dest = path.normalize(path.join(path.dirname(fileName), ref))
          if (!wanted.has(dest)) wanted.set(dest, path.basename(ref))
        }
      }

      const missing = []
      for (const [dest, basename] of wanted) {
        const target = path.join(outDir, dest)
        if (fs.existsSync(target)) continue
        const found = searchRoots
          .map((root) => path.join(root, basename))
          .find((candidate) => fs.existsSync(candidate))
        if (!found) {
          missing.push(dest)
          continue
        }
        fs.mkdirSync(path.dirname(target), { recursive: true })
        fs.copyFileSync(found, target)
      }

      if (missing.length) {
        this.error(
          'These fonts are referenced by the built CSS but no source was found:\n  ' +
            missing.join('\n  ') +
            '\nAdd its directory to shipFontsReferencedByCss({ searchRoots }).',
        )
      }
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig(async ({ mode }) => {
  const isDev = mode === 'development'
  const config = {
    plugins: [
      vue(),
      vueJsx(),
      // Both layouts the repo builds in: frappe-ui resolves through
      // node_modules inside a bench, and as a sibling checkout from the
      // working tree. Roots that do not exist are simply never matched.
      shipFontsReferencedByCss({
        searchRoots: [
          path.resolve(
            import.meta.dirname,
            'node_modules/@fontsource-variable/plus-jakarta-sans/files',
          ),
          path.resolve(
            import.meta.dirname,
            'node_modules/frappe-ui/src/fonts/Inter',
          ),
          path.resolve(import.meta.dirname, '../frappe-ui/src/fonts/Inter'),
        ],
      }),
      /**
       * Scope has to be stated twice, because the plugin's default is wrong here.
       *
       * `--base=/assets/crm/frontend/` is where the built files *land*; `/crm`
       * is where Frappe *serves* them. vite-plugin-pwa derives both the manifest
       * scope and the worker's registration scope from base, which produced a
       * manifest whose scope excluded its own start_url — invalid, so Chrome
       * declined to prompt — and a worker scoped to the asset directory, which
       * can never control the page it exists to cache. Neither failed loudly:
       * the app just quietly had no working PWA.
       *
       * A worker served from /assets/... may only claim /crm if its response
       * carries `Service-Worker-Allowed: /crm`; deploy/nginx/security_headers.conf
       * adds it. Without that header registration fails with a SecurityError and
       * the app runs on with no worker — the page itself is unaffected, so a
       * deployment that misses the header degrades rather than breaks.
       */
      VitePWA({
        registerType: 'autoUpdate',
        scope: '/crm',
        workbox: {
          maximumFileSizeToCacheInBytes: 8 * 1024 * 1024,
          // Never answer a navigation from the cache. The built index.html is
          // a Jinja template: Frappe renders it as /crm with the session's
          // boot -- csrf_token, user, translations -- inlined. Precaching it
          // and serving it as the navigation fallback handed every reload the
          // *raw* file: `{% for key in boot %}` failed to parse, window had no
          // csrf_token, and every POST answered CSRFTokenError until the
          // worker's cache was cleared by hand. Observed on production within
          // hours of the worker first claiming /crm. The shell must always
          // come from the server; only the hashed assets are cacheable.
          navigateFallback: null,
          globIgnores: ['**/index.html'],
        },
        devOptions: {
          enabled: true,
        },
        manifest: {
          display: 'standalone',
          scope: '/crm',
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
        // reka-ui carries the dialog's title/description context. A second copy
        // would provide into different injection keys, so `DialogTitle` in this
        // app would silently stop naming frappe-ui's `DialogContent`.
        'reka-ui',
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
        // Maps only for dev builds — a production bundle shipped 154 .map
        // files (a 6.8 MB one for Dashboard alone) to every browser.
        sourcemap: isDev,
      },
    }),
  )

  return config
})

function resolveFrameworkUi() {
  // Two layouts carry the real package: building through the bench symlink
  // (frappe-bench/apps/crm/frontend) and building from the working tree with
  // the bench checked out beside it. Both are guesses about where the bench
  // sits relative to this file, and node resolves import.meta.dirname through
  // symlinks, so the first only matches when the app is a real subdirectory of
  // the bench rather than a link into it.
  //
  // FRAPPE_UI_SRC names it outright for layouts neither guess covers -- the
  // devcontainer keeps its bench on a volume at /home/frappe/frappe-bench,
  // outside the repo entirely, and sets this in docker-compose.yml.
  const candidates = [
    process.env.FRAPPE_UI_SRC,
    path.resolve(import.meta.dirname, '../../frappe/ui/src'),
    path.resolve(import.meta.dirname, '../frappe-bench/apps/frappe/ui/src'),
  ].filter(Boolean)
  const stub = path.resolve(import.meta.dirname, 'src/lib/framework-ui-stub')
  if (process.env.FRAMEWORK_UI_STUB === '1') {
    console.info('@framework/ui: stub forced via FRAMEWORK_UI_STUB=1')
    return stub
  }
  const real = candidates.find((p) => fs.existsSync(p))
  if (real) return real

  // Falling back silently is how a bundle of no-ops ships looking healthy: the
  // Data Import page renders nothing, useOnboarding returns zeros at eight call
  // sites, and every product event is dropped -- none of which fails a build or
  // a test. A warning in a log nobody reads is not a guard, so refuse instead.
  // Building deliberately without a bench is still supported; it just has to be
  // said out loud, which is also what records the intent in CI's workflow file.
  throw new Error(
    '@framework/ui: no bench sibling found. Checked:\n' +
      candidates.map((p) => `  ${p}`).join('\n') +
      '\nBuild from a bench, point FRAPPE_UI_SRC at its apps/frappe/ui/src, or ' +
      'set FRAMEWORK_UI_STUB=1 to build against the no-op stub on purpose ' +
      '(see src/lib/framework-ui-stub/README.md).',
  )
}

async function importFrappeUIPlugin(isDev, config) {
  if (isDev) {
    try {
      // Opt-in dev override: build against a local frappe-ui checkout instead
      // of the pinned npm package, for iterating on the two together. This
      // used to be a git submodule, removed because its pinned commit no
      // longer exists upstream — so the path is now yours to create or not:
      //
      //   git clone https://github.com/frappe/frappe-ui <repo-root>/frappe-ui
      //
      // Absent, the block below is skipped and the npm package is used; that
      // is the normal path and the only one CI and production builds take.
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
