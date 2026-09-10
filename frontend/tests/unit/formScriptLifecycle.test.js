import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * A source guard, because the thing being asserted is a *shape* and the module
 * it lives in cannot be imported here: `data/document.js` pulls frappe-ui's
 * resource plugin in at module scope, which needs a browser.
 *
 * Two defects, both invisible at runtime:
 *
 * 1. onLoad, onRender, onSave and onError were called without an await and
 *    without a catch. onValidate was fixed to toast; these four stayed silent,
 *    so a script that threw in one of them left a record with no scripted
 *    behaviour, no message, and an unhandled rejection in a console nobody was
 *    reading.
 *
 * 2. `controllersCache[...] = {}` was written *before* the await on
 *    `setupScript`, as a re-entrancy guard. It doubled as a permanent
 *    "already tried" marker, so a script that failed to evaluate was never
 *    tried again for that record -- not even on a fresh mount.
 */
const source = readFileSync(join(process.cwd(), 'src/data/document.js'), 'utf8')

describe('form script lifecycle hooks', () => {
  it.each([
    'triggerOnLoad',
    'triggerOnRender',
    'triggerOnSave',
    'triggerOnError',
  ])('%s is never called as a bare statement', (trigger) => {
    // A bare `triggerOnLoad()` alone on its line is the fire-and-forget
    // call whose rejection nothing handles. Passed as an argument it ends in
    // a comma, and awaited it is preceded by `await`, so neither matches.
    expect(source).not.toMatch(
      new RegExp(`^\\s*${trigger}\\([^)]*\\)\\s*$`, 'm'),
    )
  })

  it('routes hook failures through one reporter', () => {
    expect(
      source.match(/reportScriptFailure\(/g)?.length,
    ).toBeGreaterThanOrEqual(5)
    // The reporter must toast, not only log: silence was the bug.
    const reporter = source.match(
      /function reportScriptFailure\([\s\S]*?\n\}/,
    )?.[0]
    expect(reporter).toBeTruthy()
    expect(reporter).toMatch(/validationErrorMessage\(/)
    expect(reporter).toMatch(/toast\.error\(/)
  })
})

describe('form script setup', () => {
  it('caches controllers only after the script has evaluated', () => {
    const await_at = source.indexOf('await setupScript(')
    expect(await_at).toBeGreaterThan(-1)

    const writes = [...source.matchAll(/controllersCache\[doctype\]\[\w+\] =/g)]
    expect(writes.length).toBeGreaterThan(0)
    for (const write of writes) {
      expect(write.index).toBeGreaterThan(await_at)
    }
  })

  it('guards re-entrancy with an in-flight promise instead', () => {
    expect(source).toMatch(/const setupPromises = \{\}/)
    expect(source).toMatch(/setupPromises\[doctype\]\[\w+\] = /)
    // and lets go of it once settled, so a failed setup can be retried
    expect(source).toMatch(/delete setupPromises\[doctype\]\[\w+\]/)
  })
})
