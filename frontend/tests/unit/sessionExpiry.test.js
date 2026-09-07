import { describe, expect, it } from 'vitest'
import { isSessionGone, loginUrlFor, currentUserCookie } from '@/utils/sessionExpiry'

const GUEST = 'sid=Guest; user_id=Guest; system_user=no'
const REP = 'sid=abc123; user_id=rep%40example.com; system_user=yes'

describe('isSessionGone', () => {
  it('treats frappe\'s session_expired marker as gone', () => {
    expect(isSessionGone({ status: 403, session_expired: 1 }, REP)).toBe(true)
  })
  it('treats an AuthenticationError as gone', () => {
    expect(isSessionGone({ status: 401, exc_type: 'AuthenticationError' }, REP)).toBe(true)
  })
  it('a 403 with the user cookie gone is an expired session', () => {
    expect(isSessionGone({ status: 403, exc_type: 'PermissionError' }, GUEST)).toBe(true)
    expect(isSessionGone({ status: 403, exc_type: 'PermissionError' }, '')).toBe(true)
  })
  it('a 403 while still logged in is a real permission refusal', () => {
    expect(isSessionGone({ status: 403, exc_type: 'PermissionError' }, REP)).toBe(false)
  })
  it('other failures are not session problems', () => {
    expect(isSessionGone({ status: 500, exc_type: 'ValidationError' }, GUEST)).toBe(false)
    expect(isSessionGone({ status: 417, exc_type: 'ValidationError' }, REP)).toBe(false)
    expect(isSessionGone(null, GUEST)).toBe(false)
  })
})

describe('loginUrlFor', () => {
  it('carries the whole location so the person returns where they were', () => {
    const url = loginUrlFor({ pathname: '/crm/deals/CRM-DEAL-1', search: '?view=x', hash: '#emails' })
    expect(url).toBe('/login?redirect-to=' + encodeURIComponent('/crm/deals/CRM-DEAL-1?view=x#emails'))
  })
})

describe('currentUserCookie', () => {
  it('decodes the user id', () => {
    expect(currentUserCookie(REP)).toBe('rep@example.com')
    expect(currentUserCookie(undefined)).toBeNull()
  })
})
