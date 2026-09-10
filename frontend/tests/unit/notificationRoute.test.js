import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { notificationKey, notificationRoute } from '@/utils/notificationRoute'

/** A row shaped like `crm.api.notifications.get_notifications` returns one. */
function row(overrides = {}) {
  return {
    creation: '2026-09-08 11:04:22.113455',
    type: 'Mention',
    read: false,
    hash: '#a8f21c0b9d',
    notification_type_doctype: 'Comment',
    notification_type_doc: 'a8f21c0b9d',
    reference_doctype: 'deal',
    reference_name: 'CRM-DEAL-2026-00042',
    route_name: 'Deal',
    ...overrides,
  }
}

describe('notificationRoute', () => {
  it('uses the hash the server worked out', () => {
    // The page built `'#' + notification.comment` -- a field the payload does
    // not carry -- so every tap navigated to the literal string '#undefined'
    // and the record opened on the last-used tab instead of the comment.
    expect(notificationRoute(row()).hash).toBe('#a8f21c0b9d')
  })

  it('carries no hash when the notification names no anchor', () => {
    expect(notificationRoute(row({ hash: '' })).hash).toBe('')
    expect(notificationRoute(row({ hash: undefined })).hash).toBe('')
  })

  it('never produces the string "#undefined"', () => {
    for (const value of [undefined, null, '']) {
      expect(notificationRoute(row({ hash: value })).hash).not.toContain(
        'undefined',
      )
    }
  })

  it('names the deal param for a deal and the lead param otherwise', () => {
    expect(notificationRoute(row()).params).toEqual({
      dealId: 'CRM-DEAL-2026-00042',
    })
    const lead = row({
      route_name: 'Lead',
      reference_name: 'CRM-LEAD-2026-00007',
    })
    expect(notificationRoute(lead).params).toEqual({
      leadId: 'CRM-LEAD-2026-00007',
    })
    expect(notificationRoute(lead).name).toBe('Lead')
  })

  it('passes the whatsapp and task anchors straight through', () => {
    expect(notificationRoute(row({ hash: '#whatsapp' })).hash).toBe('#whatsapp')
    expect(notificationRoute(row({ hash: '#tasks' })).hash).toBe('#tasks')
  })
})

describe('notificationKey', () => {
  it('tells two rows apart', () => {
    const a = notificationKey(row())
    const b = notificationKey(row({ notification_type_doc: 'ff01b2' }))
    expect(a).not.toBe(b)
  })

  it('is stable across reloads of the same row', () => {
    expect(notificationKey(row())).toBe(notificationKey(row()))
  })

  it('is never undefined', () => {
    // `:key="n.comment"` keyed every row as undefined.
    expect(notificationKey({})).not.toContain('undefined')
    expect(notificationKey(undefined)).not.toContain('undefined')
  })
})

// --- source guards ----------------------------------------------------------

function read(relative) {
  return readFileSync(join(process.cwd(), relative), 'utf8')
}

describe('the notifications page', () => {
  const page = read('src/pages/MobileNotification.vue')

  it('tells a failed fetch apart from an empty inbox', () => {
    expect(page).toMatch(/<ErrorState\s+v-else-if="notifications\.error"/)
  })

  it('marks the whole inbox read explicitly', () => {
    // `mark_as_read.reload()` re-sent whatever params were left on the shared
    // resource, so a failed per-document mark turned the next "mark all" into
    // "mark that one again".
    expect(page).not.toMatch(/mark_as_read\.reload\(\)/)
    expect(page).toMatch(/mark_all_as_read\(\)/)
  })
})

describe('the notifications store', () => {
  const store = read('src/stores/notifications.js')

  it('clears the single-document params on failure too', () => {
    const onError = store.match(/onError: \(\) => \{[\s\S]*?\n {4}\}/)?.[0]
    expect(onError).toMatch(/mark_as_read\.params = \{\}/)
  })

  it('sends empty params for mark-all rather than reusing the last ones', () => {
    expect(store).toMatch(/function mark_all_as_read\(\)[\s\S]*?submit\(\{\}\)/)
  })
})

describe('socket listeners', () => {
  /** Every `$socket.off(...)` call in src, with the file it came from. */
  function offCalls() {
    function walk(dir) {
      return readdirSync(dir).flatMap((entry) => {
        const full = join(dir, entry)
        if (statSync(full).isDirectory()) return walk(full)
        return /\.(vue|js)$/.test(full) ? [full] : []
      })
    }
    const src = join(process.cwd(), 'src')
    return walk(src).flatMap((file) =>
      [...readFileSync(file, 'utf8').matchAll(/\$socket\.off\(([^)]*)\)/g)].map(
        (m) => ({ file: file.slice(src.length + 1), args: m[1] }),
      ),
    )
  }

  it.each([
    'pages/MobileNotification.vue',
    'pages/Deal.vue',
    'components/Activities/Activities.vue',
  ])('%s removes only its own listener', (file) => {
    // socket.io's off with one argument removes *every* listener on the event.
    // A desktop user who opened /notifications from a bookmark and clicked away
    // stopped the bell and the panel updating for the rest of the session.
    const calls = offCalls().filter((c) => c.file === file)
    expect(calls.length).toBeGreaterThan(0)
    for (const call of calls) {
      expect(call.args, `${file}: $socket.off(${call.args})`).toContain(',')
    }
  })
})
