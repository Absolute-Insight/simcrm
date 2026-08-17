import { beforeEach, describe, expect, it, vi } from 'vitest'

/* frappe-ui does not resolve under vitest (its plugin entry points at a source
   path that is not shipped), and the toast is a side effect anyway — the
   factory keeps the real package from ever loading. */
const toast = { error: vi.fn() }
vi.mock('frappe-ui', () => ({ toast }))

const { actionErrorMessage, reportActionError } = await import(
  '@/utils/reportActionError'
)

describe('actionErrorMessage', () => {
  it("prefers the server's own sentence over any generic copy", () => {
    /* The reason a rep can act on is almost always the one the server wrote:
       "linked to a Quotation" tells them what to do, "something went wrong"
       does not. */
    const error = {
      status: 417,
      _server_messages: JSON.stringify([
        JSON.stringify({ message: 'Cannot delete: linked to a Quotation' }),
      ]),
    }
    expect(actionErrorMessage(error, 'Could not delete.')).toBe(
      'Cannot delete: linked to a Quotation',
    )
  })

  it('strips the HTML frappe wraps its messages in', () => {
    const error = {
      status: 417,
      _server_messages: JSON.stringify([
        JSON.stringify({ message: '<b>Not permitted</b><br>Ask an admin' }),
      ]),
    }
    expect(actionErrorMessage(error)).toBe('Not permitted Ask an admin')
  })

  it('names a permission failure rather than blaming the server', () => {
    expect(actionErrorMessage({ status: 403 })).toBe(
      'You do not have permission to do that.',
    )
  })

  it('names a dropped connection', () => {
    const error = new TypeError('Failed to fetch')
    expect(actionErrorMessage(error)).toBe(
      'Cannot reach the server. Check your connection and try again.',
    )
  })

  it('names a record that has gone', () => {
    expect(actionErrorMessage({ status: 404 })).toBe(
      'That record is not here any more.',
    )
  })

  it("uses the caller's sentence when the server wrote nothing usable", () => {
    expect(actionErrorMessage({ status: 500 }, 'Could not assign.')).toBe(
      'Could not assign.',
    )
  })

  it('never returns an empty string, whatever it is handed', () => {
    // A toast with no text is indistinguishable from the silence this exists
    // to end.
    for (const input of [null, undefined, '', 0, {}, [], new Error()]) {
      expect(actionErrorMessage(input)).toBeTruthy()
    }
  })

  it('does not claim the change was not made', () => {
    /* This layer cannot know: a dropped connection may still have reached the
       server, and a 500 can arrive after the write. Promising otherwise is the
       kind of false reassurance that sends a rep to re-enter work that was
       already saved. */
    const messages = [
      actionErrorMessage(new TypeError('Failed to fetch')),
      actionErrorMessage({ status: 500 }),
      actionErrorMessage({ status: 403 }),
    ]
    for (const message of messages) {
      expect(message.toLowerCase()).not.toContain('nothing was changed')
      expect(message.toLowerCase()).not.toContain('was not saved')
    }
  })
})

describe('reportActionError', () => {
  beforeEach(() => {
    toast.error.mockClear()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('shows the rep a sentence and hands the raw error to the console', () => {
    const error = { status: 403 }
    const returned = reportActionError(error, 'Could not assign.')

    expect(toast.error).toHaveBeenCalledWith(
      'You do not have permission to do that.',
    )
    expect(returned).toBe('You do not have permission to do that.')
    // The sentence is for the rep; the stack is for whoever they report it to.
    expect(console.error).toHaveBeenCalledWith(error)
  })

  it('always shows something, even for an error with nothing in it', () => {
    reportActionError(undefined)
    expect(toast.error).toHaveBeenCalledTimes(1)
    expect(toast.error.mock.calls[0][0]).toBeTruthy()
  })
})
