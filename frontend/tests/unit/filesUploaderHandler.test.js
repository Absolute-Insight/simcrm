import { describe, expect, it } from 'vitest'
import {
  parseUploadFailure,
  safeJsonParse,
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
