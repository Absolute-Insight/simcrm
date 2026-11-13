import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Coloured text takes the -9 step (AGENTS.md, Design system gotchas): the
 * --ink-{green,red,orange} ladders are readability ladders, so a low step is
 * a background tint in both themes. The sender label on a quoted WhatsApp
 * reply was `text-ink-green-5`, about 2.7:1 on the light theme.
 */
describe('WhatsAppArea coloured text', () => {
  const source = fs.readFileSync(
    path.resolve(
      import.meta.dirname,
      '../../src/components/Activities/WhatsAppArea.vue',
    ),
    'utf8',
  )

  it('uses no ink step below -9 for green, red or orange text', () => {
    const steps = [
      ...source.matchAll(/text-ink-(green|red|orange|amber)-(\d+)/g),
    ].map((m) => `${m[1]}-${m[2]}`)
    expect(steps).toContain('green-9')
    expect(steps.filter((step) => !step.endsWith('-9'))).toEqual([])
  })
})
