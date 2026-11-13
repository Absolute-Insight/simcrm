import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  HEAVY_LIBRARIES,
  OFFLINE_ROOTS,
  SERVER_ONLY,
  planPrecache,
} from '@/utils/precachePlan'

const RULES = {
  heavy: HEAVY_LIBRARIES,
  offlineRoots: OFFLINE_ROOTS,
  serverOnly: SERVER_ONLY,
}
const SRC = '/app/frontend/src'
const LIB = '/app/frontend/node_modules'

/** A chunk as the vite plugin describes it. `modules` is {id: [on-demand ids]}. */
const chunk = (fileName, modules, { imports = [], isEntry = false } = {}) => ({
  fileName,
  isEntry,
  imports,
  modules: Object.entries(modules).map(([id, dynamicImports]) => ({
    id,
    dynamicImports,
  })),
})

/** The app in miniature: a boot, the route table, field mode, heavy pages. */
function build({ fieldImports = [], fieldLoads = [], bootLoads = {} } = {}) {
  return [
    chunk(
      'index.js',
      {
        [`${SRC}/main.js`]: [],
        [`${SRC}/router.js`]: [
          `${SRC}/pages/Dashboard.vue`,
          `${SRC}/pages/Leads.vue`,
          `${SRC}/pages/Field.vue`,
          `${SRC}/components/Field/FieldToday.vue`,
        ],
        [`${SRC}/App.vue?vue&type=script&setup=true&lang.js`]: [
          `${SRC}/components/Layouts/DesktopLayout.vue`,
        ],
        ...bootLoads,
      },
      { isEntry: true, imports: ['vendor.js'] },
    ),
    chunk('vendor.js', { [`${LIB}/vue/dist/vue.js`]: [] }),
    chunk('Dashboard.js', {
      [`${SRC}/pages/Dashboard.vue`]: [],
      [`${LIB}/echarts/lib/echarts.js`]: [],
    }),
    chunk(
      'Leads.js',
      { [`${SRC}/pages/Leads.vue`]: [`${SRC}/components/Modals/Edit.vue`] },
      { imports: ['vendor.js'] },
    ),
    chunk(
      'Edit.js',
      { [`${SRC}/components/Modals/Edit.vue`]: [] },
      { imports: ['TextEditor.js'] },
    ),
    chunk('TextEditor.js', { [`${LIB}/@tiptap/core/dist/index.js`]: [] }),
    chunk('DesktopLayout.js', {
      [`${SRC}/components/Layouts/DesktopLayout.vue`]: [
        `${LIB}/@twilio/voice-sdk/es5/twilio.js`,
      ],
    }),
    chunk('twilio.js', { [`${LIB}/@twilio/voice-sdk/es5/twilio.js`]: [] }),
    chunk('sprite.js', { [`${LIB}/lucide-static/sprite.svg?raw`]: [] }),
    chunk('leaflet.js', { [`${LIB}/leaflet/dist/leaflet-src.js`]: [] }),
    chunk(
      'Field.js',
      { [`${SRC}/pages/Field.vue`]: fieldLoads },
      { imports: ['vendor.js', 'useField.js', ...fieldImports] },
    ),
    chunk('useField.js', { [`${SRC}/offline/useField.js`]: [] }),
    chunk('FieldToday.js', {
      [`${SRC}/components/Field/FieldToday.vue`]: [],
    }),
  ]
}
const lazy = (chunks) => [...planPrecache(chunks, RULES).lazy].sort()
const kept = (chunks) =>
  planPrecache(chunks, RULES)
    .kept.map((k) => k.fileName)
    .sort()

describe('planPrecache', () => {
  it('leaves out the heavy chunks only server pages reach', () => {
    expect(lazy(build())).toEqual([
      'Dashboard.js',
      'TextEditor.js',
      'leaflet.js',
      'sprite.js',
      'twilio.js',
    ])
    expect(kept(build())).toEqual([])
  })

  it('never leaves out a chunk that holds no heavy library', () => {
    const { lazy: out } = planPrecache(build(), RULES)
    for (const name of [
      'index.js',
      'vendor.js',
      'Leads.js',
      'Edit.js',
      'DesktopLayout.js',
      'Field.js',
      'useField.js',
      'FieldToday.js',
    ]) {
      expect(out.has(name)).toBe(false)
    }
  })

  it('keeps a heavy chunk a field page imports', () => {
    const chunks = build({ fieldImports: ['leaflet.js'] })
    expect(kept(chunks)).toEqual(['leaflet.js'])
    expect(lazy(chunks)).not.toContain('leaflet.js')
  })

  it('keeps a heavy chunk a field page loads on demand, and what that imports', () => {
    const chunks = build({
      fieldLoads: [`${SRC}/components/Modals/Edit.vue`],
    })
    expect(kept(chunks)).toEqual(['TextEditor.js'])
    expect(planPrecache(chunks, RULES).kept[0].via).toEqual([
      'TextEditor.js',
      'Edit.js',
      'Field.js',
    ])
  })

  it('keeps a heavy chunk the boot loads on demand outside the route table', () => {
    // the icon sprite: asked for by a component in the entry, used everywhere
    const chunks = build({
      bootLoads: {
        [`${SRC}/utils/lucideSprite.js`]: [
          `${LIB}/lucide-static/sprite.svg?raw`,
        ],
      },
    })
    expect(kept(chunks)).toEqual(['sprite.js'])
  })

  it('keeps a heavy chunk the entry imports statically', () => {
    const chunks = build()
    chunks[0].imports.push('twilio.js')
    expect(kept(chunks)).toEqual(['twilio.js'])
  })

  it('does not follow the record form or the shell from the boot', () => {
    const chunks = build({
      bootLoads: {
        [`${SRC}/components/Modals/DoctypeModals.vue`]: [
          `${SRC}/components/Modals/Edit.vue`,
        ],
      },
    })
    expect(lazy(chunks)).toContain('TextEditor.js')
    expect(lazy(chunks)).toContain('twilio.js') // through the layout
  })

  it('follows what any module under offline/ loads on demand', () => {
    const chunks = build()
    chunks.push(
      chunk('odd.js', {
        [`${SRC}/offline/router.js`]: [`${LIB}/leaflet/dist/leaflet-src.js`],
      }),
    )
    expect(kept(chunks)).toEqual(['leaflet.js'])
  })
})

describe('planPrecache and an on-demand import it cannot place', () => {
  it('says so once, and plans the rest as before', () => {
    const warnings = []
    const chunks = build({
      fieldLoads: ['/somewhere/else/missing.js', '/somewhere/else/missing.js'],
    })
    const plan = planPrecache(chunks, {
      ...RULES,
      warn: (message) => warnings.push(message),
    })
    expect(warnings).toHaveLength(1)
    expect(warnings[0]).toContain('/somewhere/else/missing.js')
    expect(warnings[0]).toContain('pages/Field.vue')
    expect([...plan.lazy].sort()).toEqual(lazy(build()))
  })

  it('is silent for a build where every import lands in a chunk', () => {
    const warnings = []
    planPrecache(build(), { ...RULES, warn: (m) => warnings.push(m) })
    expect(warnings).toEqual([])
  })
})

describe('the precache rules against this codebase', () => {
  const root = path.resolve(import.meta.dirname, '../..')
  const router = fs.readFileSync(path.join(root, 'src/router.js'), 'utf8')

  it('name every page the router marks offline', () => {
    // One offline branch, /field. Another one needs adding to OFFLINE_ROOTS,
    // or its chunks may be left out of the precache it depends on.
    expect(router.match(/offline:\s*true/g)).toHaveLength(1)
    const start = router.indexOf("path: '/field'")
    expect(start).toBeGreaterThan(-1)
    const branch = router.slice(start, router.indexOf('\n  },\n', start))
    expect(branch).toMatch(/offline:\s*true/)
    const pages = [...branch.matchAll(/import\('@\/([^']+)'\)/g)].map(
      (m) => `${root}/src/${m[1]}`,
    )
    expect(pages.length).toBeGreaterThan(1)
    for (const page of pages) {
      expect(fs.existsSync(page)).toBe(true)
      expect(OFFLINE_ROOTS.some((p) => p.test(page))).toBe(true)
    }
  })

  it('name the modules that exist', () => {
    for (const file of [
      'src/router.js',
      'src/App.vue',
      'src/components/Modals/DoctypeModals.vue',
    ]) {
      expect(fs.existsSync(path.join(root, file))).toBe(true)
      expect(SERVER_ONLY.some((p) => p.test(`${root}/${file}`))).toBe(true)
    }
    // vite names a .vue module's script with a query after the path
    expect(
      SERVER_ONLY.some((p) =>
        p.test(`${root}/src/App.vue?vue&type=script&setup=true&lang.js`),
      ),
    ).toBe(true)
  })

  it('wire the plan into the worker without loosening what the audit verified', () => {
    const config = fs.readFileSync(path.join(root, 'vite.config.js'), 'utf8')
    expect(config).toContain("globIgnores: ['**/index.html']")
    expect(config).toContain('navigateFallback: null')
    expect(config).toContain('manifestTransforms')
    // the runtime cache takes this build's hashed files and nothing else
    const pattern =
      /^\/assets\/crm\/frontend\/assets\/[^/]+-[\w-]{8}\.(?:js|css)$/
    expect(config).toContain(pattern.source)
    for (const cached of [
      '/assets/crm/frontend/assets/Dashboard-DI42NpjV.js',
      '/assets/crm/frontend/assets/L.Control.Locate.esm-NlVJ8UeM.js',
      '/assets/crm/frontend/assets/TextEditor-WZA8zovD.css',
    ]) {
      expect(pattern.test(cached)).toBe(true)
    }
    for (const never of [
      '/api/method/crm.api.session.get_users',
      '/api/method/frappe.client.get_list',
      '/crm',
      '/crm/leads/view',
      '/assets/crm/frontend/index.html',
      '/assets/crm/frontend/shell.html',
      '/assets/crm/frontend/sw.js',
      '/files/quote-abcdefgh.js',
      '/private/files/report-abcdefgh.css',
      '/assets/crm/frontend/assets/sub/dir-abcdefgh.js',
    ]) {
      expect(pattern.test(never)).toBe(false)
    }
  })
})
