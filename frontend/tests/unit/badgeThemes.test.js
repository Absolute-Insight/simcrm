import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Badge falls back to `gray` for a theme it does not recognise.
 *
 * That is the right behaviour for a component — better a neutral badge than a
 * crash — but it means a typo is invisible: `theme="orange"` rendered fifteen
 * warning badges in neutral grey beside the red ones, so the middle tier of
 * every warning in the app simply did not exist. Nothing failed, nothing
 * logged, and the only way to notice was to know what colour it should be.
 *
 * So the enum is asserted from outside. This reads Badge's own `themeClasses`
 * rather than restating the list, because a copy here would drift the same way
 * the call sites did.
 */

/* Resolved from cwd (vitest's root is `frontend/`) rather than import.meta.url,
   which vitest hands back with a `/@fs` prefix that node's fs cannot open.
   Badge comes from node_modules, not the sibling frappe-ui checkout: the
   checkout is a local convenience, the package is what CI installs and what
   actually ships. */
const SRC = join(process.cwd(), 'src')
const BADGE = join(
  process.cwd(),
  'node_modules',
  'frappe-ui',
  'src',
  'components',
  'Badge',
  'Badge.vue',
)

function validThemes() {
  const source = readFileSync(BADGE, 'utf8')
  const block = source.match(/const themeClasses = \{(.*?)\n\}/s)
  if (!block) {
    throw new Error(
      'Badge.vue no longer declares themeClasses as expected — this guard must ' +
        'be updated with it, not deleted.',
    )
  }
  return [...block[1].matchAll(/^ {2}(\w+):/gm)].map((m) => m[1])
}

function vueFiles(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return vueFiles(full)
    return full.endsWith('.vue') ? [full] : []
  })
}

/**
 * Every literal `theme="..."` written on a `<Badge>`, with the file it came from.
 *
 * Scoped to Badge tags on purpose. A scan for any `theme=` attribute reports
 * two things that are not bugs: a *bound* `:theme="theme"` forwarding a prop to
 * a Button, and `[data-theme="dark"]` inside a CSS comment. Other components
 * have their own theme enums, and this guard is not about them.
 *
 * Only unbound literals are checked — `:theme="expr"` is a runtime value this
 * cannot evaluate, and pretending otherwise would be a guard that looks broader
 * than it is.
 */
function literalThemes() {
  return vueFiles(SRC).flatMap((file) => {
    const source = readFileSync(file, 'utf8')
    return [...source.matchAll(/<Badge\b[^>]*>/g)].flatMap((tag) =>
      [...tag[0].matchAll(/(?<![:\w-])theme="([a-z]+)"/g)].map((m) => ({
        file: file.slice(SRC.length + 1),
        theme: m[1],
      })),
    )
  })
}

describe('Badge themes', () => {
  it('reads a real enum out of Badge.vue', () => {
    // Guards the guard: an empty enum would make every assertion below vacuous.
    const themes = validThemes()
    expect(themes).toContain('amber')
    expect(themes).toContain('red')
    expect(themes.length).toBeGreaterThan(3)
  })

  it('finds theme literals to check', () => {
    expect(literalThemes().length).toBeGreaterThan(10)
  })

  it('uses no theme the component would silently drop to grey', () => {
    const valid = new Set(validThemes())
    const unknown = literalThemes().filter((t) => !valid.has(t.theme))
    expect(
      unknown.map((u) => `${u.file}: theme="${u.theme}"`),
      'these render as neutral grey instead of the tier they name',
    ).toEqual([])
  })

  it('specifically has no orange left', () => {
    // Named because it is the one that shipped, fifteen times.
    expect(literalThemes().filter((t) => t.theme === 'orange')).toEqual([])
  })
})
