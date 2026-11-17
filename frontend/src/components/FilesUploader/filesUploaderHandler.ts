interface UploadOptions {
  fileObj?: File
  private?: boolean
  fileUrl?: string
  folder?: string
  doctype?: string
  docname?: string
  fieldname?: string
  type?: string
}

type EventListenerOption = 'start' | 'progress' | 'finish' | 'error'

declare global {
  interface Window {
    csrf_token?: string
  }
}

/**
 * JSON.parse that returns the raw text instead of throwing.
 *
 * Frappe answers a 403 with an HTML sign-in page often enough that parsing it
 * blind is not an edge case, and a throw inside `onreadystatechange` does not
 * reject anything — it escapes the handler and leaves the upload promise
 * pending for the life of the tab. The spinner never stops and no error is
 * ever shown.
 */
export function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/**
 * What a non-200 upload response means: the error to reject with, and whether
 * it counts against the handler's `failed` flag.
 *
 * 403 deliberately does not set `failed` — that is the pre-existing behaviour
 * and it is what lets a re-auth retry proceed.
 */
export function parseUploadFailure(
  status: number,
  responseText: string,
): { error: unknown; failed: boolean } {
  if (status === 413) {
    return {
      error: 'Size exceeds the maximum allowed file size.',
      failed: true,
    }
  }
  return { error: safeJsonParse(responseText), failed: status !== 403 }
}

/**
 * The sentence to show for a rejected upload, never throwing.
 *
 * FilesUploader's catch used to parse `_server_messages` and `exc` blind. Both
 * are JSON strings nested in JSON, and either can be malformed or not what we
 * expect; a throw there skipped the rest of the catch, so a failed file was
 * left in the list with no error beside it and a web link was toasted a
 * SyntaxError. Whatever the shape, this returns text.
 */
export function uploadErrorMessage(error: unknown, fallback: string): string {
  if (typeof error === 'string') return error.trim() || fallback
  if (!error || typeof error !== 'object') return fallback

  const { _server_messages, exc } = error as {
    _server_messages?: unknown
    exc?: unknown
  }

  if (typeof _server_messages === 'string') {
    const entries = safeJsonParse(_server_messages)
    const first = Array.isArray(entries) ? entries[0] : undefined
    const parsed = typeof first === 'string' ? safeJsonParse(first) : first
    const message =
      parsed && typeof parsed === 'object'
        ? (parsed as { message?: unknown }).message
        : parsed
    if (typeof message === 'string' && message.trim()) return message
  }

  if (typeof exc === 'string') {
    const frames = safeJsonParse(exc)
    const trace = Array.isArray(frames) ? frames[0] : undefined
    if (typeof trace === 'string') {
      // The last line of a Python traceback is the exception and its message.
      const last = trace.trim().split('\n').pop()?.trim()
      if (last) return last
    }
  }

  return fallback
}

class FilesUploadHandler {
  listeners: { [event: string]: ((...args: unknown[]) => void)[] }
  failed: boolean

  constructor() {
    this.listeners = {}
    this.failed = false
  }

  on(event: EventListenerOption, handler: (...args: unknown[]) => void) {
    this.listeners[event] = this.listeners[event] || []
    this.listeners[event].push(handler)
  }

  trigger(event: string, data?: unknown) {
    const handlers = this.listeners[event] || []
    handlers.forEach((handler) => {
      handler.call(this, data)
    })
  }

  upload(file: File | null, options: UploadOptions): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.upload.addEventListener('loadstart', () => {
        this.trigger('start')
      })
      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
          this.trigger('progress', {
            uploaded: e.loaded,
            total: e.total,
          })
        }
      })
      xhr.upload.addEventListener('load', () => {
        this.trigger('finish')
      })
      xhr.addEventListener('error', () => {
        this.trigger('error')
        reject()
      })
      xhr.onreadystatechange = () => {
        if (xhr.readyState !== XMLHttpRequest.DONE) return

        if (xhr.status === 200) {
          const body = safeJsonParse(xhr.responseText)
          resolve((body as { message?: unknown })?.message ?? body)
          return
        }

        const { error, failed } = parseUploadFailure(
          xhr.status,
          xhr.responseText,
        )
        if (failed) this.failed = true

        const exc = (error as { exc?: unknown })?.exc
        if (typeof exc === 'string') {
          const frames = safeJsonParse(exc)
          console.error(Array.isArray(frames) ? frames[0] : exc)
        }
        reject(error)
      }

      xhr.open('POST', '/api/method/upload_file', true)
      xhr.setRequestHeader('Accept', 'application/json')

      if (window.csrf_token && window.csrf_token !== '{{ csrf_token }}') {
        xhr.setRequestHeader('X-Frappe-CSRF-Token', window.csrf_token)
      }

      const formData = new FormData()

      if (options.fileObj && file?.name) {
        formData.append('file', options.fileObj, file.name)
      }
      formData.append('is_private', options.private || false ? '1' : '0')
      formData.append('folder', options.folder || 'Home')

      if (options.fileUrl) {
        formData.append('file_url', options.fileUrl)
      }

      if (options.doctype) {
        formData.append('doctype', options.doctype)
      }

      if (options.docname) {
        formData.append('docname', options.docname)
      }

      if (options.fieldname) {
        formData.append('fieldname', options.fieldname)
      }

      if (options.type) {
        formData.append('type', options.type)
      }

      xhr.send(formData)
    })
  }
}

export default FilesUploadHandler
