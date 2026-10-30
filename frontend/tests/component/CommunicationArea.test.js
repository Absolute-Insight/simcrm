import { defineComponent, h, nextTick, reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// Node's own file-less localStorage global shadows happy-dom's; give the
// drafts a working in-memory one, as a browser would.
const store = new Map()
const memoryStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  clear: () => store.clear(),
  key: (i) => [...store.keys()][i] ?? null,
  get length() {
    return store.size
  },
}
for (const target of [globalThis, window]) {
  Object.defineProperty(target, 'localStorage', {
    value: memoryStorage,
    configurable: true,
  })
}

const S = vi.hoisted(() => ({ calls: [], seen: {} }))

// The composers record the props CommunicationArea hands them; the real ones
// push an upload into their `attachments` array.
const { composer } = vi.hoisted(() => ({
  composer: (name) => ({
    default: {
      name,
      inheritAttrs: false,
      setup(_, { attrs, expose }) {
        S.seen[name] = attrs
        expose({
          editor: {
            commands: { focus: () => {}, setContent: () => {} },
            getHTML: () => '',
          },
          toEmails: ['buyer@customer.co.za'],
        })
        return () => null
      },
    },
  }),
}))
vi.mock('@/components/EmailEditor.vue', () => composer('EmailEditor'))
vi.mock('@/components/CommentBox.vue', () => composer('CommentBox'))
vi.mock('frappe-ui', () => ({
  call: (method, args) => {
    S.calls.push({ method, args })
    return Promise.resolve({ name: 'CMT-1' })
  },
  createResource: () => reactive({ data: null }),
  toast: { promise: () => 'toast-id', error: () => {} },
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    getUser: () => ({ email: 'rep@example.com', full_name: 'Rep' }),
  }),
}))

const { default: CommunicationArea } = await import(
  '@/components/CommunicationArea.vue'
)

const Button = defineComponent({ setup: () => () => h('button') })

const quote = {
  name: 'FILE-0001',
  file_name: 'quotation-rev3.pdf',
  file_url: '/private/files/quotation-rev3.pdf',
}

async function flush() {
  for (let i = 0; i < 5; i++) {
    await Promise.resolve()
    await nextTick()
  }
}

async function open() {
  mount(CommunicationArea, {
    props: {
      modelValue: {
        name: 'CRM-DEAL-2026-00042',
        email: 'buyer@customer.co.za',
      },
      doctype: 'CRM Deal',
    },
    stubs: { Button },
  })
  await flush()
  // The rep attaches the quotation to the email draft...
  S.seen.EmailEditor.attachments.push(quote)
  await flush()
  return S.seen
}

describe('CommunicationArea draft attachments', () => {
  beforeEach(() => {
    store.clear()
    S.calls.length = 0
    S.seen = {}
  })

  it('keeps the email draft files out of the comment box', async () => {
    const { CommentBox } = await open()
    expect(CommentBox.attachments).toEqual([])
  })

  it('leaves the email draft files alone when a comment is discarded', async () => {
    const { EmailEditor, CommentBox } = await open()
    // ...then writes an internal note instead, and discards it.
    await CommentBox.discardButtonProps.onClick()
    await flush()

    expect(S.calls.filter((c) => c.method === 'frappe.client.delete')).toEqual(
      [],
    )
    expect(EmailEditor.attachments.map((a) => a.name)).toEqual(['FILE-0001'])
  })

  it('does not post the email draft files with a comment', async () => {
    const { EmailEditor, CommentBox } = await open()
    CommentBox['onUpdate:content']('<p>internal: check pricing first</p>')
    await flush()
    await CommentBox.submitButtonProps.onClick()
    await flush()

    const post = S.calls.find((c) => c.method === 'crm.api.comment.add_comment')
    expect(post.args.attachments).toEqual([])
    expect(EmailEditor.attachments.map((a) => a.name)).toEqual(['FILE-0001'])
  })

  it('still deletes the email draft files when the email is discarded', async () => {
    const { EmailEditor } = await open()
    await EmailEditor.discardButtonProps.onClick()
    await flush()

    expect(S.calls.filter((c) => c.method === 'frappe.client.delete')).toEqual([
      {
        method: 'frappe.client.delete',
        args: { doctype: 'File', name: 'FILE-0001' },
      },
    ])
  })
})
