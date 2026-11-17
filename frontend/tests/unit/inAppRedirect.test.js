import { describe, expect, it } from 'vitest'
import { inAppRedirectPath } from '@/utils/inAppRedirect'

describe('inAppRedirectPath', () => {
  it('keeps a path inside the app, with its query', () => {
    expect(inAppRedirectPath('/deals?view=3')).toBe('/deals?view=3')
  })

  it('refuses anything that could leave the app', () => {
    for (const target of [
      undefined,
      null,
      ['/deals'],
      '',
      'deals',
      'https://evil.example',
      '//evil.example',
      '/\\evil.example',
    ]) {
      expect(inAppRedirectPath(target)).toBe('/')
    }
  })

  it('does not loop back to the Load Failed page', () => {
    expect(inAppRedirectPath('/load-failed?redirect=/deals')).toBe('/')
    expect(inAppRedirectPath('/load-failed')).toBe('/')
    expect(inAppRedirectPath('/load-failed-reports')).toBe(
      '/load-failed-reports',
    )
  })
})
