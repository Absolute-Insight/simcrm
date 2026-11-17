import { readFileSync } from 'node:fs'
import path from 'node:path'
import { compile } from 'tailwindcss'
import { describe, expect, it } from 'vitest'

/**
 * frappe-ui's Select, in popper mode (any of side/align/offset set), sizes its
 * menu with `min-w-[--reka-select-trigger-width]`: tailwind-3 shorthand that
 * tailwind 4 emits verbatim, as a declaration the browser drops. So every
 * `side="bottom"` select opened narrower than its field. index.css restates
 * the rule with the var() it meant.
 */
const root = path.resolve(import.meta.dirname, '../..')
const CLASS = 'min-w-[--reka-select-trigger-width]'
const selectSource = readFileSync(
  path.join(root, 'node_modules/frappe-ui/src/components/Select/Select.vue'),
  'utf8',
)
const indexCss = readFileSync(path.join(root, 'src/index.css'), 'utf8')

async function tailwindFor(className) {
  const twDir = path.join(root, 'node_modules/tailwindcss')
  const compiler = await compile('@import "tailwindcss/utilities";', {
    base: root,
    loadStylesheet: async () => {
      const file = path.join(twDir, 'utilities.css')
      return { path: file, base: twDir, content: readFileSync(file, 'utf8') }
    },
  })
  return compiler.build([className])
}

describe('a bottom-placed select menu', () => {
  it('is at least as wide as its field', async () => {
    if (!selectSource.includes(CLASS)) {
      // frappe-ui fixed it upstream: delete the rule in index.css and this.
      expect(indexCss).not.toContain('--reka-select-trigger-width')
      return
    }
    // still broken as tailwind emits it...
    expect(await tailwindFor(CLASS)).toMatch(
      /min-width:\s*--reka-select-trigger-width;/,
    )
    // ...so the app restates it
    expect(indexCss).toMatch(
      /\[data-slot='content'\]\.min-w-\\\[--reka-select-trigger-width\\\]\s*\{\s*min-width:\s*var\(--reka-select-trigger-width\);/,
    )
  })
})
