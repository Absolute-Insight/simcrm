import { describe, expect, it } from 'vitest'
import { fontDestination } from '../../scripts/cssFontRefs.mjs'

const BASE = '/assets/crm/frontend/'

describe('fontDestination', () => {
  it('resolves a relative url against the stylesheet', () => {
    expect(
      fontDestination('assets/index-abc.css', './Inter.var-x.woff2', BASE),
    ).toBe('assets/Inter.var-x.woff2')
    expect(
      fontDestination('assets/index-abc.css', 'Inter.var-x.woff2', BASE),
    ).toBe('assets/Inter.var-x.woff2')
    expect(fontDestination('assets/css/a.css', '../fonts/a.woff2', BASE)).toBe(
      'assets/fonts/a.woff2',
    )
  })

  // vite 8.3.6 writes these; joined onto the stylesheet's directory they came
  // out as assets/assets/crm/frontend/assets/... and failed the build.
  it('takes an absolute url under the base as a path inside the output', () => {
    expect(
      fontDestination(
        'assets/index-abc.css',
        '/assets/crm/frontend/assets/Inter.var-x.woff2',
        BASE,
      ),
    ).toBe('assets/Inter.var-x.woff2')
  })

  it('accepts a base written without its trailing slash', () => {
    expect(
      fontDestination(
        'assets/a.css',
        '/assets/crm/frontend/assets/a.woff2',
        '/assets/crm/frontend',
      ),
    ).toBe('assets/a.woff2')
  })

  it('leaves alone what this build does not serve', () => {
    expect(
      fontDestination('assets/a.css', '/files/brand.woff2', BASE),
    ).toBeNull()
    expect(
      fontDestination('assets/a.css', '/assets/crm/frontendish/a.woff2', BASE),
    ).toBeNull()
    expect(
      fontDestination('assets/a.css', 'https://cdn.example/a.woff2', BASE),
    ).toBeNull()
    expect(
      fontDestination('assets/a.css', '//cdn.example/a.woff2', BASE),
    ).toBeNull()
    expect(
      fontDestination('assets/a.css', 'data:font/woff2;base64,AAAA', BASE),
    ).toBeNull()
  })

  it('works with the dev server base of /', () => {
    expect(fontDestination('assets/a.css', '/assets/a.woff2', '/')).toBe(
      'assets/a.woff2',
    )
  })
})
