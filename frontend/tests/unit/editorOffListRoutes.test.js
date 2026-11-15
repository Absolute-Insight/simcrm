import fs from 'node:fs'
import path from 'node:path'
import { parse } from '@vue/compiler-sfc'
import { describe, expect, it } from 'vitest'

/**
 * The rich-text editor (tiptap, ProseMirror, lowlight: 284 KB gzipped) is
 * fetched with anything that can reach an import of it through static imports
 * alone. A list page draws no editor, and neither does the app shell around
 * it, so nothing either imports statically may lead to one: what does draw an
 * editor there -- a settings page, the call window's note, the bulk-edit
 * dialog, a Text Editor field -- loads it on first use
 * (utils/lazyComponent.js, components/Controls/LazyTextEditor.js).
 *
 * The first version of this walked from the list pages only. They came out
 * clean and every one of them still fetched the editor, because the shell
 * they are drawn inside imported it: Settings and the call window, both
 * mounted by the layouts. So the walk starts where the browser does -- the
 * entry, then whatever App.vue loads to draw any page, then the page.
 *
 * It follows `import ... from` edges. A dynamic `import()` is not followed --
 * that is what loading on first use looks like -- except from App.vue, whose
 * dynamic imports are the layouts: one of them is fetched on every visit, so
 * for this purpose they are static.
 *
 * This is the source graph, not the chunks rollup writes from it: a shared
 * helper placed in the editor's chunk would put the editor back without any
 * import changing. That shows only in a build -- sum what each chunk imports
 * statically, from the entry and a layout to the route's chunk.
 */
const SRC = path.resolve(import.meta.dirname, '../../src')
// clause (what is imported) and specifier (where from) of each static import
const STATIC_IMPORT =
  /^[ \t]*(?:import|export)\s+(?:([^'"]*?)\s+from\s+)?['"]([^'"]+)['"]/gm
const DYNAMIC_IMPORT = /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g

/** Does this import statement bring in the editor? */
function isEditorImport(clause, spec) {
  // types are erased by the build
  if (/^type\s/.test(clause ?? '')) return false
  if (spec === 'frappe-ui/editor') return true
  if (/^(@tiptap\/|prosemirror-|lowlight$|highlight\.js)/.test(spec))
    return true
  // the experimental barrel holds much else; only its editor counts
  return spec === 'frappe-ui/experimental' && /\bTextEditor\w*\b/.test(clause)
}

function resolve(spec, from) {
  let base
  if (spec.startsWith('@/')) base = path.join(SRC, spec.slice(2))
  else if (spec.startsWith('.')) base = path.resolve(path.dirname(from), spec)
  else return null
  const candidates = [
    base,
    ...['.js', '.ts', '.vue', '.jsx'].map((ext) => base + ext),
    path.join(base, 'index.js'),
    path.join(base, 'index.ts'),
  ]
  return candidates.find((c) => fs.existsSync(c) && fs.statSync(c).isFile())
}

const scripts = new Map()
function scriptOf(file) {
  if (scripts.has(file)) return scripts.get(file)
  let text = fs.readFileSync(file, 'utf8')
  if (file.endsWith('.vue')) {
    // the compiler's own reading of the file, both script blocks
    const { script, scriptSetup } = parse(text, { filename: file }).descriptor
    text = [script, scriptSetup].map((block) => block?.content ?? '').join('\n')
  }
  scripts.set(file, text)
  return text
}

const src = (relative) => path.join(SRC, relative)
const name = (file) => path.relative(SRC, file)

/** The modules `file` loads on demand, as files. */
function dynamicImports(file) {
  return [...scriptOf(file).matchAll(DYNAMIC_IMPORT)]
    .map(([, spec]) => resolve(spec, file))
    .filter(Boolean)
}

/** Every module statically reachable from `roots`, with how it was reached. */
function staticClosure(roots) {
  const parent = new Map(roots.map((root) => [root, null]))
  const queue = [...roots]
  while (queue.length) {
    const file = queue.shift()
    for (const [, , spec] of scriptOf(file).matchAll(STATIC_IMPORT)) {
      const target = resolve(spec, file)
      if (target && !parent.has(target)) {
        parent.set(target, file)
        queue.push(target)
      }
    }
  }
  return parent
}

/** Each way the editor is statically reached from `roots`, as a chain. */
function editorChains(roots) {
  const parent = staticClosure(roots)
  return [...parent.keys()]
    .filter((file) =>
      [...scriptOf(file).matchAll(STATIC_IMPORT)].some(([, clause, spec]) =>
        isEditorImport(clause, spec),
      ),
    )
    .map((file) => {
      const chain = []
      for (let at = file; at; at = parent.get(at)) chain.push(name(at))
      return chain.join(' <- ')
    })
}

const ENTRY = src('main.js')
const APP = src('App.vue')
// what App.vue fetches to draw any page at all
const LAYOUTS = dynamicImports(APP)
const SHELL = [ENTRY, ...LAYOUTS]
const page = (title) => src(`pages/${title}.vue`)

describe('the rich-text editor stays off the boot, the shell and the list routes', () => {
  it('walks the shell the app really mounts', () => {
    // If App.vue stops loading its layouts this way, or the layouts stop
    // mounting these, the checks below would pass by looking at nothing.
    expect(staticClosure([ENTRY]).has(APP)).toBe(true)
    expect(LAYOUTS.map(name).sort()).toEqual([
      'components/Layouts/DesktopLayout.vue',
      'components/Layouts/MobileLayout.vue',
    ])
    for (const layout of LAYOUTS) {
      const reached = [...staticClosure([layout]).keys()].map(name)
      expect(reached).toEqual(
        expect.arrayContaining([
          'components/Modals/GlobalModals.vue',
          'components/Settings/Settings.vue',
          'components/Telephony/CallUI.vue',
        ]),
      )
    }
  })

  it('the entry reaches no editor import statically', () => {
    expect(editorChains([ENTRY])).toEqual([])
  })

  it.each(LAYOUTS.map((layout) => [name(layout), layout]))(
    'the shell (%s) reaches no editor import statically',
    (_, layout) => {
      expect(editorChains([layout])).toEqual([])
    },
  )

  it('the global modals reach no editor import statically', () => {
    expect(editorChains([src('components/Modals/GlobalModals.vue')])).toEqual(
      [],
    )
  })

  it.each([
    'Leads',
    'Deals',
    'Contacts',
    'Organizations',
    'CallLogs',
    'Dashboard',
    // draws an editor only in the panel of an event that has been opened
    'Calendar',
  ])('%s, inside the shell, reaches no editor import statically', (title) => {
    expect(editorChains([...SHELL, page(title)])).toEqual([])
  })

  it('still finds the editor where a page does draw one', () => {
    // the walk itself, checked against pages that import it on purpose:
    // both draw read-only editors in their cards on first paint
    expect(editorChains([page('Notes')])).toEqual(['pages/Notes.vue'])
    expect(editorChains([page('Tasks')]).length).toBeGreaterThan(0)
    // and against each way of importing it
    expect(isEditorImport('{ TextEditor }', 'frappe-ui/experimental')).toBe(
      true,
    )
    expect(isEditorImport('{ ListFooter }', 'frappe-ui/experimental')).toBe(
      false,
    )
    expect(isEditorImport('{ useEditor }', 'frappe-ui/editor')).toBe(true)
    expect(isEditorImport('Paragraph', '@tiptap/extension-paragraph')).toBe(
      true,
    )
    expect(isEditorImport('type { Extension }', '@tiptap/core')).toBe(false)
  })
})
