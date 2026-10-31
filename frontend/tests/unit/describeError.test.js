import { describe, expect, it, vi } from 'vitest'
import { describeError } from '@/utils/describeError'

describe('describeError', () => {
  it('reports nothing for an absent error', () => {
    expect(describeError(null)).toEqual({
      kind: 'none',
      message: '',
      detail: '',
    })
    expect(describeError(undefined).kind).toBe('none')
    expect(describeError('').kind).toBe('none')
  })

  it('takes a bare string as the message', () => {
    expect(describeError('Could not save')).toEqual({
      kind: 'unknown',
      message: 'Could not save',
      detail: '',
    })
  })

  it('promotes the first server message', () => {
    const result = describeError({
      messages: ['Deal is already closed', 'Reopen it first'],
      exc_type: 'ValidationError',
    })
    expect(result.message).toBe('Deal is already closed')
    expect(result.detail).toContain('Reopen it first')
    expect(result.detail).toContain('ValidationError')
  })

  it('renders Frappe message markup as plain text', () => {
    const result = describeError({
      messages: ['<b>Row 3:</b>&nbsp;Value &lt;required&gt;'],
    })
    expect(result.message).toBe('Row 3: Value <required>')
  })

  it('unpacks _server_messages, JSON inside JSON', () => {
    const raw = JSON.stringify([JSON.stringify({ message: 'Quota not set' })])
    expect(describeError({ _server_messages: raw }).message).toBe(
      'Quota not set',
    )
  })

  it('falls back to the raw string when _server_messages is malformed', () => {
    expect(describeError({ _server_messages: 'not json at all' }).message).toBe(
      'not json at all',
    )
  })

  it('classifies a dropped connection as offline', () => {
    const err = new TypeError('Failed to fetch')
    const result = describeError(err)
    expect(result.kind).toBe('offline')
    // The browser's wording is a diagnostic, not a sentence for the user.
    expect(result.message).toBe('')
    expect(result.detail).toContain('Failed to fetch')
  })

  it('recognises the other browsers phrasings of a network failure', () => {
    expect(describeError(new TypeError('Load failed')).kind).toBe('offline')
    expect(
      describeError(
        new TypeError('NetworkError when attempting to fetch resource.'),
      ).kind,
    ).toBe('offline')
    expect(describeError({ status: 0, message: 'boom' }).kind).toBe('offline')
  })

  it('classifies permission failures from either the exc type or the status', () => {
    expect(describeError({ exc_type: 'PermissionError' }).kind).toBe(
      'permission',
    )
    expect(describeError({ status: 403 }).kind).toBe('permission')
    expect(describeError({ status: 401 }).kind).toBe('permission')
  })

  it('classifies a missing document', () => {
    expect(describeError({ exc_type: 'DoesNotExistError' }).kind).toBe(
      'notfound',
    )
    expect(describeError({ status: 404 }).kind).toBe('notfound')
  })

  it('classifies a server fault', () => {
    expect(describeError({ status: 500 }).kind).toBe('server')
    expect(describeError({ exc_type: 'ValidationError' }).kind).toBe('server')
  })

  it('does not promote a transport message into the face', () => {
    const result = describeError({
      status: 500,
      message: 'Internal Server Error',
    })
    expect(result.message).toBe('')
    expect(result.detail).toContain('Internal Server Error')
    expect(result.detail).toContain('HTTP 500')
  })

  it('keeps the traceback in the detail only', () => {
    const result = describeError({
      exc_type: 'ValidationError',
      messages: ['Enter a number of 0 or more.'],
      exc: 'Traceback (most recent call last):\n  File "quotas.py", line 12',
    })
    expect(result.message).toBe('Enter a number of 0 or more.')
    expect(result.message).not.toContain('Traceback')
    expect(result.detail).toContain('Traceback (most recent call last)')
  })

  it('unwraps an error nested one level deeper', () => {
    const result = describeError({
      error: { messages: ['Nested reason'], exc_type: 'PermissionError' },
    })
    expect(result.kind).toBe('permission')
    expect(result.message).toBe('Nested reason')
  })

  it('unwraps a nested string reason', () => {
    expect(describeError({ error: 'Plain reason' }).message).toBe(
      'Plain reason',
    )
  })

  it('prefers the outer messages when both levels carry them', () => {
    const result = describeError({
      messages: ['Outer reason'],
      error: { messages: ['Inner reason'] },
    })
    expect(result.message).toBe('Outer reason')
  })

  it('never repeats the promoted message inside the detail', () => {
    const result = describeError({
      messages: ['Only reason'],
      message: 'Only reason',
    })
    expect(result.detail).not.toContain('Only reason')
  })

  it('does not print the message twice above its own stack', () => {
    const err = new TypeError('Failed to fetch')
    err.stack = 'TypeError: Failed to fetch\n    at fetchAll (resource.js:1)'
    const detail = describeError(err).detail
    expect(detail.match(/Failed to fetch/g)).toHaveLength(1)
  })

  it('prefers the server traceback over the browser stack', () => {
    const err = new Error('Request failed')
    err.exc = 'Traceback: crm/api/reports.py'
    const detail = describeError(err).detail
    expect(detail).toContain('crm/api/reports.py')
    expect(detail).not.toContain('describeError.test')
  })

  it('handles an error that carries nothing useful', () => {
    const result = describeError({})
    expect(result).toEqual({ kind: 'unknown', message: '', detail: '' })
  })
})

/* The errors above are hand-built. These come from frappe-ui's own
   frappeRequest, which fills `messages` with a placeholder of its own when the
   server wrote none: an unhandled exception (a 500 without frappe.throw) or a
   gateway's HTML 504 then read "Internal Server Error", untranslated, where
   the caller's sentence belonged. */
describe('describeError on what frappeRequest throws', () => {
  async function failWith(status, body) {
    const { frappeRequest } = await import(
      '../../node_modules/frappe-ui/src/utils/frappeRequest.ts'
    )
    vi.stubGlobal('fetch', async () => new Response(body, { status }))
    vi.spyOn(console, 'log').mockImplementation(() => {})
    try {
      await frappeRequest({ url: 'crm.api.dashboard.get_chart' })
    } catch (error) {
      return error
    } finally {
      vi.unstubAllGlobals()
      vi.restoreAllMocks()
    }
    throw new Error('the request did not fail')
  }

  it('an unhandled server exception leaves the face to the caller', async () => {
    const error = await failWith(
      500,
      JSON.stringify({ exc_type: 'TypeError', exc: '["Traceback: boom"]' }),
    )
    expect(error.messages).toEqual(['Internal Server Error']) // the placeholder
    const result = describeError(error)
    expect(result.kind).toBe('server')
    expect(result.message).toBe('')
    expect(result.detail).toContain('HTTP 500')
  })

  it("a gateway's HTML 504 leaves the face to the caller", async () => {
    const error = await failWith(
      504,
      '<html><body>504 Gateway Time-out</body></html>',
    )
    const result = describeError(error)
    expect(result.kind).toBe('server')
    expect(result.message).toBe('')
  })

  it('still promotes what the server wrote for a person', async () => {
    const error = await failWith(
      417,
      JSON.stringify({
        exc_type: 'ValidationError',
        _server_messages: JSON.stringify([
          JSON.stringify({ message: 'Enter a number of 0 or more.' }),
        ]),
      }),
    )
    expect(describeError(error).message).toBe('Enter a number of 0 or more.')
  })

  it("still promotes the server's _error_message", async () => {
    const error = await failWith(
      404,
      JSON.stringify({
        exc_type: 'DoesNotExistError',
        _error_message: 'CRM Deal CRM-DEAL-9 not found',
      }),
    )
    expect(describeError(error).message).toBe('CRM Deal CRM-DEAL-9 not found')
  })
})
