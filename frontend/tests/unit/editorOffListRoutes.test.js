import fs from 'node:fs'
import path from 'node:path'
import { parse } from '@vue/compiler-sfc'
import { describe, expect, it } from 'vitest'

/**
 * The rich-text editor (tiptap, ProseMirror, lowlight: 284 KB gzipped) is
 * fetched with any page that can reach an import of it through static
 * imports alone. A list page draws no editor, so nothing it imports
 * statically may lead to one: the bulk-edit dialog and the Text Editor field
 * control are loaded on first use (utils/lazyComponent.js).
 *
 * This walks `import ... from` edges from each list page. A dynamic
 * `import()` is not followed -- that is what loading on first use looks like.
 */
const SRC = path.resolve(import.meta.dirname, '../../src')
const STATIC_IMPORT =
  /^\s*(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]/gm
const EDITOR_IMPORT =
  /import\s*\{[^}]*\bTextEditor\b[^}]*\}\s*from\s*['"]frappe-ui\/experimental['"]/

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

function scriptOf(file) {
  const text = fs.readFileSync(file, 'utf8')
  if (!file.endsWith('.vue')) return text
  // the compiler's own reading of the file, both script blocks
  const { script, scriptSetup } = parse(text, { filename: file }).descriptor
  return [script, scriptSetup].map((block) => block?.content ?? '').join('\n')
}

/** Every module statically reachable from `start`, with how it was reached. */
function staticClosure(start) {
  const parent = new Map([[start, null]])
  const queue = [start]
  while (queue.length) {
    const file = queue.shift()
    for (const [, spec] of scriptOf(file).matchAll(STATIC_IMPORT)) {
      const target = resolve(spec, file)
      if (target && !parent.has(target)) {
        parent.set(target, file)
        queue.push(target)
      }
    }
  }
  return parent
}

function editorChains(page) {
  const parent = staticClosure(path.join(SRC, 'pages', `${page}.vue`))
  return [...parent.keys()]
    .filter((file) => EDITOR_IMPORT.test(scriptOf(file)))
    .map((file) => {
      const chain = []
      for (let at = file; at; at = parent.get(at)) {
        chain.push(path.relative(SRC, at))
      }
      return chain.join(' <- ')
    })
}

describe('the rich-text editor stays off the list routes', () => {
  it.each(['Leads', 'Deals', 'Contacts', 'Organizations', 'CallLogs'])(
    '%s reaches no editor import statically',
    (page) => {
      expect(editorChains(page)).toEqual([])
    },
  )

  it('still finds the editor where a page does draw one', () => {
    // the walk itself, checked against a page that imports it on purpose
    expect(editorChains('Notes').length).toBeGreaterThan(0)
  })
})
