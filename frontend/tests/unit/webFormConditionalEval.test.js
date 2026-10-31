import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { describe, expect, it } from 'vitest'

// Load the inline conditional-logic parser straight out of crm_form.html (the guest
// page's security boundary) so we test the exact code that ships, not a copy.
const html = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    '../../../crm/www/crm_form.html',
  ),
  'utf8',
)
const src = html
  .split('// [conditional-eval:start]')[1]
  .split('// [conditional-eval:end]')[0]
// eslint-disable-next-line no-new-func
const { truthy } = new Function(`${src}; return { truthy };`)()

describe('crm_form.html conditional-logic evaluator', () => {
  const doc = { organization: 'Acme', first_name: 'Al', n: '10', items: [1] }

  describe('correctness', () => {
    it('plain fieldname → truthiness', () => {
      expect(truthy('organization', doc, false)).toBe(true)
      expect(truthy('missing', doc, false)).toBe(false)
    })
    it('eval: comparisons and logic', () => {
      expect(truthy('eval:doc.organization == "Acme"', doc, false)).toBe(true)
      expect(truthy('eval:doc.organization == "Other"', doc, false)).toBe(false)
      expect(truthy('eval:doc.n > 5', doc, false)).toBe(true)
      expect(
        truthy('eval:doc.first_name && doc.organization', doc, false),
      ).toBe(true)
      expect(truthy('eval:!doc.missing', doc, false)).toBe(true)
      expect(
        truthy(
          'eval:(doc.a || doc.organization) && doc.first_name',
          doc,
          false,
        ),
      ).toBe(true)
    })
    it('empty/blank expression → fallback', () => {
      expect(truthy('', doc, true)).toBe(true)
      expect(truthy('   ', doc, false)).toBe(false)
    })
    it('array field → non-empty truthiness', () => {
      expect(truthy('items', doc, false)).toBe(true)
    })
  })

  describe('security — never executes arbitrary JS, always falls back', () => {
    const attacks = [
      'eval:window',
      'eval:document',
      'eval:globalThis',
      'eval:fetch("/x")',
      'eval:alert(1)',
      'eval:doc.constructor.constructor("return 1")()',
      'eval:(0).constructor.constructor("return 1")()',
      'eval:doc.x = 1',
    ]
    for (const expr of attacks) {
      it(`rejects ${expr}`, () => {
        // any parse error → fallback is returned, so the expression never runs
        expect(truthy(expr, doc, false)).toBe(false)
        expect(truthy(expr, doc, true)).toBe(true)
      })
    }
    it('cannot cause side effects on globals', () => {
      globalThis.__pwned = false
      truthy('eval:(globalThis.__pwned = true)', doc, false)
      expect(globalThis.__pwned).toBe(false)
      delete globalThis.__pwned
    })
  })
})

// The server stores only what this parser accepts (crm.api.form._is_safe_condition,
// a port of it), because frappe's own /<route> page runs a stored condition as
// code. Both are run against the same list so the two cannot drift apart.
const conditions = JSON.parse(
  readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      '../../../crm/tests/public_form_conditions.json',
    ),
    'utf8',
  ),
)
// a parsed expression ignores the fallback; one it refuses returns it
const parses = (expr) =>
  truthy(expr, { a: 1, n: 3 }, true) === truthy(expr, { a: 1, n: 3 }, false)

describe('crm_form.html evaluator agrees with the server-side store check', () => {
  it.each(conditions.accepted)('parses %j', (expr) => {
    expect(parses(expr)).toBe(true)
  })
  it.each(conditions.rejected)('refuses %j', (expr) => {
    expect(parses(expr)).toBe(false)
  })
})
