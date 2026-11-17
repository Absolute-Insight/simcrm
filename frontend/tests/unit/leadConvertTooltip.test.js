import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * The disabled Convert to Deal button sits in the page header. Its tooltip
 * opened on frappe-ui's default top side, found no room above the header,
 * flipped down and covered the record ID at the top of the side panel.
 */
const lead = readFileSync(
  path.resolve(import.meta.dirname, '../../src/pages/Lead.vue'),
  'utf8',
)

describe("the lead page's Convert to Deal tooltip", () => {
  it('opens beside the button, not over the side panel', () => {
    const tag = lead.match(
      /<Tooltip\b[^>]*Cannot convert a lost lead to deal[^>]*>/,
    )
    expect(tag).not.toBeNull()
    expect(tag[0]).toMatch(/\bside="left"/)
  })
})
