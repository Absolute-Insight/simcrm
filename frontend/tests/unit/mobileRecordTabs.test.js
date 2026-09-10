import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * The mobile Deal and Lead pages build their own tab list rather than sharing
 * the desktop one, and it had silently fallen behind: both omitted Events.
 * Nothing on a phone showed a record's meetings -- and the Calendar nav entry
 * is hidden on mobile -- so a rep who accepted a "Schedule call" suggestion, or
 * whose week the planner had filled in, could not see the time they had agreed
 * to. Activities already renders the pane; only the tab was missing.
 */
function tabNames(page) {
  const source = readFileSync(join(process.cwd(), 'src/pages', page), 'utf8')
  const options = source.match(/let tabOptions = \[([\s\S]*?)\n {2}\]/)?.[1]
  if (!options) throw new Error(`could not find ${page}'s tabOptions array`)
  return [...options.matchAll(/name: '([^']+)'/g)].map((m) => m[1])
}

describe('mobile record tabs', () => {
  it.each(['MobileDeal.vue', 'MobileLead.vue'])('%s offers Events', (page) => {
    expect(tabNames(page)).toContain('Events')
  })

  it.each([
    ['MobileDeal.vue', 'Deal.vue'],
    ['MobileLead.vue', 'Lead.vue'],
  ])('%s offers nothing the desktop page does not', (mobile, desktop) => {
    // Details is the mobile-only side panel; everything else must exist on the
    // desktop page too, or the two lists have drifted again.
    const extra = tabNames(mobile).filter(
      (name) => name !== 'Details' && !tabNames(desktop).includes(name),
    )
    expect(extra).toEqual([])
  })

  it('puts Events where the desktop page puts it, after Data', () => {
    for (const page of ['MobileDeal.vue', 'MobileLead.vue', 'Deal.vue']) {
      const names = tabNames(page)
      expect(names.indexOf('Events'), page).toBe(names.indexOf('Data') + 1)
    }
  })
})
