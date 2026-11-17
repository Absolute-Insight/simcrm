import { describe, expect, it } from 'vitest'
import {
  parseUploadFailure,
  safeJsonParse,
  uploadErrorMessage,
} from '@/components/FilesUploader/filesUploaderHandler'

describe('safeJsonParse', () => {
  it('parses a JSON body', () => {
    expect(safeJsonParse('{"message":"ok"}')).toEqual({ message: 'ok' })
  })

  it('returns the raw text instead of throwing on an HTML error page', () => {
    /* The whole bug: a throw here escapes onreadystatechange without calling
       reject, so the upload promise never settles and the spinner runs
       forever. */
    const html = '<!DOCTYPE html><html><body>Not permitted</body></html>'
    expect(() => safeJsonParse(html)).not.toThrow()
    expect(safeJsonParse(html)).toBe(html)
  })

  it('survives an empty body', () => {
    expect(safeJsonParse('')).toBe('')
  })
})

describe('parseUploadFailure', () => {
  it('reads a JSON error body', () => {
    const { error, failed } = parseUploadFailure(
      417,
      '{"exc_type":"Validation"}',
    )
    expect(error).toEqual({ exc_type: 'Validation' })
    expect(failed).toBe(true)
  })

  it('does not throw on a 403 that returns an HTML sign-in page', () => {
    const html = '<html><body>Login</body></html>'
    expect(() => parseUploadFailure(403, html)).not.toThrow()
    expect(parseUploadFailure(403, html).error).toBe(html)
  })

  it('leaves `failed` unset for a 403, so a retry after re-auth can proceed', () => {
    expect(parseUploadFailure(403, '{}').failed).toBe(false)
  })

  it('explains a 413 rather than echoing the server body', () => {
    // nginx answers 413 with its own HTML, which says nothing a rep can act on.
    const { error, failed } = parseUploadFailure(
      413,
      '<html><head><title>413 Request Entity Too Large</title></head></html>',
    )
    expect(error).toBe('Size exceeds the maximum allowed file size.')
    expect(failed).toBe(true)
  })

  it('always yields something to reject with', () => {
    for (const status of [400, 401, 403, 413, 500, 502]) {
      const { error } = parseUploadFailure(status, '')
      expect(error).toBeDefined()
    }
  })
})

describe('uploadErrorMessage', () => {
  const FALLBACK = 'Error Uploading File'

  it('reads the first server message', () => {
    const error = {
      _server_messages: JSON.stringify([
        JSON.stringify({ message: 'Invalid URL' }),
      ]),
    }
    expect(uploadErrorMessage(error, FALLBACK)).toBe('Invalid URL')
  })

  it('reads the exception line from a traceback', () => {
    const error = {
      exc: JSON.stringify([
        'Traceback (most recent call last):\n  File "x.py"\nfrappe.exceptions.ValidationError: Bad link\n',
      ]),
    }
    expect(uploadErrorMessage(error, FALLBACK)).toBe(
      'frappe.exceptions.ValidationError: Bad link',
    )
  })

  it('passes a string error through', () => {
    expect(uploadErrorMessage('Size exceeds the limit', FALLBACK)).toBe(
      'Size exceeds the limit',
    )
  })

  it('never throws on a malformed or absent error', () => {
    /* The bug: a throw inside the catch skipped the toast and the reset, so a
       web link's button kept spinning. */
    const shapes = [
      undefined,
      null,
      '',
      42,
      {},
      { _server_messages: 'not json' },
      { _server_messages: '[]' },
      { _server_messages: '["not json either"]' },
      { _server_messages: '[{"message": 5}]' },
      { _server_messages: '"a string"' },
      { exc: 'not json' },
      { exc: '[]' },
      { exc: '[null]' },
      { _server_messages: '[]', exc: '{}' },
    ]
    for (const error of shapes) {
      expect(() => uploadErrorMessage(error, FALLBACK)).not.toThrow()
      expect(uploadErrorMessage(error, FALLBACK)).toBeTruthy()
    }
  })

  it('uses a non-JSON server message as written', () => {
    expect(
      uploadErrorMessage({ _server_messages: '["Plain sentence"]' }, FALLBACK),
    ).toBe('Plain sentence')
  })

  it('falls back to the exception when server messages say nothing', () => {
    const error = {
      _server_messages: '[]',
      exc: JSON.stringify(['Traceback\nValueError: nope\n']),
    }
    expect(uploadErrorMessage(error, FALLBACK)).toBe('ValueError: nope')
  })
})
