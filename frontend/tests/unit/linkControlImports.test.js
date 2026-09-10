import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'

/**
 * `<Link>` is our own control (`src/components/Controls/Link.vue`), not one of
 * the seven components main.js registers globally and not a frappe-ui export.
 * An SFC that uses it without importing it still compiles and still renders:
 * Vue resolves the unknown name to a native element, and `<link>` is void, so
 * the picker silently disappears and the pane's own validator then refuses to
 * save for want of the value nobody could enter. DashboardSettings shipped that
 * way, which is why this is a test and not a comment.
 */

const SRC = path.resolve(import.meta.dirname, '../../src')

function vueFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return vueFiles(full)
    return entry.isFile() && entry.name.endsWith('.vue') ? [full] : []
  })
}

describe('the Link control', () => {
  it('is imported by every component that renders it', () => {
    // `\b` alone would match <LinkedDocsListView>; a tag name ends at
    // whitespace, `>` or `/`.
    const usesLink = /<Link(\s|\/|>)/
    const importsLink =
      /import\s+Link\s+from\s+['"][^'"]*Controls\/Link\.vue['"]/

    const missing = vueFiles(SRC).filter((file) => {
      const source = readFileSync(file, 'utf8')
      return usesLink.test(source) && !importsLink.test(source)
    })

    expect(missing.map((f) => path.relative(SRC, f))).toEqual([])
  })
})
