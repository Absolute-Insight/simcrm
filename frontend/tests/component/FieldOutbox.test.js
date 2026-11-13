import { describe, expect, it, vi } from 'vitest'
import { reactive, ref } from 'vue'
import { mount } from './mount.js'

const outbox = reactive({ entries: [] })
vi.mock('@/offline/outbox', () => ({
  outbox,
  retryEntry: vi.fn(),
  discardEntry: vi.fn(),
}))
const connectivity = reactive({ online: true, otherUser: false })
vi.mock('@/offline/connectivity', () => ({ connectivity }))
vi.mock('@/offline/useField', () => ({
  useField: () => ({
    pack: ref({ tasks: [] }),
    index: ref({ byName: new Map() }),
  }),
}))

const FieldOutbox = (await import('@/components/Field/FieldOutbox.vue')).default

const stubs = {
  'router-link': { template: '<a><slot /></a>' },
  Button: { props: ['label'], template: '<button>{{ label }}</button>' },
}

const task = (id, capturedAt, extra = {}) => ({
  id,
  user: 'rep@example.com',
  action: 'create_task',
  payload: { title: id },
  captured_at: capturedAt,
  status: 'pending',
  error: null,
  attempts: 0,
  ...extra,
})

describe('the outbox screen', () => {
  it('says why the entry at the head is still waiting, and that the rest wait behind it', () => {
    outbox.entries = [
      task('head', 1000, {
        error: 'The server could not take this just now.',
        attempts: 3,
      }),
      task('behind', 2000),
    ]
    const { el, unmount } = mount(FieldOutbox, { stubs })
    const [behind, head] = el.querySelectorAll('li')
    const reason = head.querySelector('[role="status"]')
    expect(reason.textContent).toContain(
      'The server could not take this just now.',
    )
    expect(reason.textContent).toContain('Tried 3 times')
    // orange, at the readable step, as a warning is
    expect(reason.className).toContain('text-ink-orange-9')
    expect(behind.textContent).toContain(
      'Waiting for an earlier entry to be sent',
    )
    expect(behind.querySelector('[role="status"]')).toBe(null)
    // the blocking entry can be thrown away from here
    expect(head.textContent).toContain('Discard')
    unmount()
  })

  it('with the line gone the last try’s reason goes too', () => {
    outbox.entries = [
      task('head', 1000, { error: 'The connection here answered instead.' }),
      task('behind', 2000),
    ]
    connectivity.online = false
    try {
      const { el, unmount } = mount(FieldOutbox, { stubs })
      expect(el.querySelector('[role="status"]')).toBe(null)
      expect(el.textContent).not.toContain('answered instead')
      expect(el.textContent).not.toContain('earlier entry')
      unmount()
    } finally {
      connectivity.online = true
    }
  })

  it('says so when the session is someone else’s and nothing is being sent', () => {
    outbox.entries = [task('mine', 1000)]
    connectivity.otherUser = true
    try {
      const { el, unmount } = mount(FieldOutbox, { stubs })
      const notice = el.querySelector('[role="alert"]')
      expect(notice.textContent).toContain('Someone else has signed in')
      expect(notice.className).toContain('text-ink-orange-9')
      unmount()
    } finally {
      connectivity.otherUser = false
    }
  })

  it('an ordinary wait says only that', () => {
    outbox.entries = [task('a', 1000), task('b', 2000)]
    const { el, unmount } = mount(FieldOutbox, { stubs })
    expect(el.querySelector('[role="status"]')).toBe(null)
    expect(el.textContent).not.toContain('earlier entry')
    expect(el.textContent).toContain('Waiting to send')
    unmount()
  })

  it('a refusal is still the server’s word, in red', () => {
    outbox.entries = [
      task('no', 1000, { status: 'rejected', error: 'This task is done.' }),
    ]
    const { el, unmount } = mount(FieldOutbox, { stubs })
    expect(el.querySelector('[role="alert"]').textContent).toContain(
      'This task is done.',
    )
    unmount()
  })
})
