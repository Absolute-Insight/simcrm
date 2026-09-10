import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { MOBILE_BREAKPOINT_PX } from '@/composables/settings'

/**
 * Source guards on the two files that decide which shell the app puts up.
 * Neither can be imported here -- `router.js` pulls frappe-ui in at module
 * scope and `App.vue` is a component, and there are no component tests -- but
 * both defects are visible in the text, and both are the kind that come back.
 */
function read(relative) {
  return readFileSync(join(process.cwd(), relative), 'utf8')
}

const routerSrc = read('src/router.js')
const appSrc = read('src/App.vue')

describe('the mobile breakpoint', () => {
  it('is one constant, at Tailwind’s md', () => {
    expect(MOBILE_BREAKPOINT_PX).toBe(768)
  })

  it('is what the router measures record pages against', () => {
    // Was a second literal 768 here against App.vue's 640, which is how an
    // iPad in split view got mobile pages inside the desktop shell.
    expect(routerSrc).toMatch(/import \{ MOBILE_BREAKPOINT_PX \}/)
    expect(routerSrc).toMatch(/window\.innerWidth < MOBILE_BREAKPOINT_PX/)
    expect(routerSrc).not.toMatch(/window\.innerWidth\s*[<>]=?\s*\d/)
  })

  it('is what the shell measures itself against', () => {
    // isMobileView is derived from the same constant, and unlike a computed
    // over window.innerWidth it actually updates when the viewport changes.
    expect(appSrc).toMatch(/import \{ isMobileView \}/)
    expect(appSrc).toMatch(
      /isMobileView\.value \? MobileLayout : DesktopLayout/,
    )
    expect(appSrc).not.toMatch(/window\.innerWidth/)
  })
})

describe('the Home redirect', () => {
  /** The `to.name === 'Home'` arm of the global guard. */
  const branch = routerSrc.slice(
    routerSrc.indexOf("to.name === 'Home'"),
    routerSrc.indexOf('} else if (!isLoggedIn)'),
  )

  it('exists', () => {
    expect(branch.length).toBeGreaterThan(100)
  })

  it('sends a rep to the Planner only when Access Control left it visible', () => {
    // It used to send every non-manager to the Planner unconditionally, so a
    // site that hid the planner for Sales User opened every rep, every login,
    // on a page with no nav entry to get back from.
    expect(branch).toMatch(/canSee\('nav\.planner'\)/)
    expect(branch).toMatch(/canSee\('nav\.planner'\) \? 'Planner' : 'Leads'/)
    expect(branch).not.toMatch(/next\(\{ name: 'Planner' \}\)/)
  })

  it('reads canSee from the store the guard already awaited', () => {
    expect(routerSrc).toMatch(/canSee,\n\s*\} = accessStore\(\)/)
  })
})
