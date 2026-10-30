import { readFileSync, statSync } from 'node:fs'
import { dirname, join, normalize } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * What every cold start parses and evaluates: the modules main.js reaches
 * through static imports. A dynamic `import()` is what lazy loading looks
 * like, so it is not followed. Package specifiers are leaves -- they are
 * recorded, not walked.
 *
 * The rich-text editor (tiptap, ProseMirror, lowlight: ~276 KB gz) used to
 * sit on this path for no page's benefit, through App.vue -> DoctypeModals ->
 * DoctypeModal -> FieldLayout -> Field -> TextEditorControl.
 */
const SRC = join(process.cwd(), 'src')
const STATIC_IMPORT =
  /^\s*import\s+(?!type\b)(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]/gm
const RE_EXPORT = /^\s*export\s+(?!type\b)[^'"]*?\s+from\s+['"]([^'"]+)['"]/gm

function resolve(spec, from) {
  let base
  if (spec.startsWith('@/')) base = join(SRC, spec.slice(2))
  else if (spec.startsWith('.')) base = normalize(join(dirname(from), spec))
  else return `pkg:${spec}`
  const candidates = [
    base,
    ...['.js', '.ts', '.vue', '.jsx'].map((ext) => base + ext),
    join(base, 'index.js'),
    join(base, 'index.ts'),
  ]
  return (
    candidates.find((c) => statSync(c, { throwIfNoEntry: false })?.isFile()) ??
    null
  )
}

function codeOf(file) {
  const text = readFileSync(file, 'utf8')
  if (!file.endsWith('.vue')) return text
  return [...text.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
    .map((m) => m[1])
    .join('\n')
}

/** module -> the module that first imported it, from main.js outward */
function bootGraph() {
  const start = join(SRC, 'main.js')
  const parent = new Map([[start, null]])
  const queue = [start]
  while (queue.length) {
    const file = queue.shift()
    if (!/\.(js|ts|vue|jsx)$/.test(file)) continue
    const code = codeOf(file)
    const specs = [
      ...[...code.matchAll(STATIC_IMPORT)].map((m) => m[1]),
      ...[...code.matchAll(RE_EXPORT)].map((m) => m[1]),
    ]
    for (const spec of specs) {
      const target = resolve(spec, file)
      if (!target || parent.has(target)) continue
      parent.set(target, file)
      if (!target.startsWith('pkg:')) queue.push(target)
    }
  }
  return parent
}

function chain(graph, node) {
  const out = []
  for (let n = node; n; n = graph.get(n)) out.push(n.replace(`${SRC}/`, ''))
  return out.join(' <- ')
}

const graph = bootGraph()
const reached = (test) =>
  [...graph.keys()].filter(test).map((n) => chain(graph, n))

describe('the static boot graph', () => {
  it('is actually walked', () => {
    expect(graph.has(join(SRC, 'App.vue'))).toBe(true)
    expect(graph.has(join(SRC, 'router.js'))).toBe(true)
  })

  it('does not carry the rich-text editor', () => {
    expect(
      reached(
        (n) =>
          n.endsWith('/TextEditorControl.vue') ||
          n.endsWith('/FieldLayout/Field.vue') ||
          /^pkg:(@tiptap\/|frappe-ui\/editor)/.test(n),
      ),
    ).toEqual([])
  })
})
