import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'

/**
 * frappe-ui 1.0 renamed or dropped these, and every one of them fails
 * silently: the old prop falls through as an inert attribute, the old slot is
 * never rendered, the old menu row renders as a bare label. None of them
 * breaks the build or a type check, and only `component:` rows warn -- in dev.
 * Each one shipped to production in v3.17.0, which is why this is a test.
 */

const SRC = path.resolve(import.meta.dirname, '../../src')

function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(full)
    return entry.isFile() && /\.(vue|js|ts)$/.test(entry.name) ? [full] : []
  })
}

const files = sourceFiles(SRC).map((file) => ({
  name: path.relative(SRC, file),
  source: readFileSync(file, 'utf8'),
}))

// The opening tag of `name`, up to `attr`. Not `[^>]*`: class strings such as
// `[&_button>span]` put a `>` inside the tag.
function inTag(name, attr) {
  return new RegExp(`<${name}\\b(?:(?!<[/A-Za-z])[\\s\\S])*?${attr}`)
}

function offenders(pattern) {
  return files.filter((f) => pattern.test(f.source)).map((f) => f.name)
}

describe('frappe-ui v0 spellings that v1 silently ignores', () => {
  it('FileUploader takes doctype/docname/private as props, not uploadArgs', () => {
    // Uploads land unattached to the record they were made from.
    expect(offenders(inTag('FileUploader', 'upload-?args'))).toEqual([])
  })

  it('TabButtons takes options, not buttons', () => {
    // The tab bar renders empty.
    expect(offenders(inTag('TabButtons', ':buttons='))).toEqual([])
  })

  it('Tabs has no #tab-item slot', () => {
    // v1 offers #tab-prefix, #tab-label and #tab-suffix instead.
    expect(offenders(/#tab-item\b/)).toEqual([])
  })

  it('menu options carry their handlers, not a component: row', () => {
    // The row renders as a plain label and the handler inside never runs.
    // Route records also use `component: () => import(...)`, so look only for
    // render functions.
    expect(
      offenders(/component:\s*\(?\w*\)?\s*=>\s*(h\(|\w+Option\()/),
    ).toEqual([])
  })
})
