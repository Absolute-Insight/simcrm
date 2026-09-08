import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * The viewport meta was missing the comma after `viewport-fit=cover`, so that
 * key parsed as `cover maximum-scale=1.0` and was dropped, and
 * `user-scalable=no` blocked pinch-zoom (WCAG 1.4.4). The Apple status-bar
 * style was "white", which is not a value the tag accepts.
 */
const html = readFileSync(
  path.resolve(import.meta.dirname, '../../index.html'),
  'utf8',
)

function metaContent(name) {
  const tag = html.match(new RegExp(`<meta\\s+name="${name}"[^>]*>`))?.[0]
  return tag?.match(/content="([^"]*)"/)?.[1] ?? null
}

function viewportPairs() {
  return Object.fromEntries(
    metaContent('viewport')
      .split(',')
      .map((part) => part.trim().split('=')),
  )
}

describe('index.html meta', () => {
  it('parses the viewport as clean key=value pairs', () => {
    for (const [key, value] of Object.entries(viewportPairs())) {
      expect(key).toMatch(/^[a-z-]+$/)
      expect(value).not.toMatch(/\s/)
    }
    expect(viewportPairs()['viewport-fit']).toBe('cover')
  })

  it('does not disable zoom', () => {
    const pairs = viewportPairs()
    expect(pairs['user-scalable']).toBeUndefined()
    expect(pairs['maximum-scale']).toBeUndefined()
  })

  it('uses a valid apple status-bar style', () => {
    expect(['default', 'black', 'black-translucent']).toContain(
      metaContent('apple-mobile-web-app-status-bar-style'),
    )
  })
})
