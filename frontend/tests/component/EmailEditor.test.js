import { defineComponent, h, reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

const S = vi.hoisted(() => ({ uploads: [], editor: null, accounts: [] }))

const { stub } = vi.hoisted(() => ({
  stub: (name) => ({
    name,
    inheritAttrs: false,
    setup:
      (_, { slots }) =>
      () =>
        slots.default?.({}),
  }),
}))

vi.mock('frappe-ui', () => ({
  FileUploader: stub('FileUploader'),
  FormControl: stub('FormControl'),
  call: () => Promise.resolve([]),
  useFileUpload: () => ({
    upload: (file, options) => {
      S.uploads.push({ file, options })
      return Promise.resolve({ file_url: '/files/' + file.name })
    },
  }),
}))
// The real editor/config builds the extensions and the upload handler; only
// the tiptap shell is stubbed, keeping the handler EmailEditor hands it.
vi.mock('frappe-ui/editor', async (importOriginal) => ({
  ...(await importOriginal()),
  Editor: {
    props: ['uploadFunction'],
    setup(props, { slots }) {
      S.editor = props
      return () => slots.default?.()
    },
  },
  EditorContent: stub('EditorContent'),
  EditorFixedMenu: stub('EditorFixedMenu'),
  EditorTableMenu: stub('EditorTableMenu'),
}))
vi.mock('@/components/IconPicker.vue', () => ({ default: stub('IconPicker') }))
vi.mock('@/components/AttachmentItem.vue', () => ({
  default: stub('AttachmentItem'),
}))
vi.mock('@/components/Controls/EmailMultiSelect.vue', () => ({
  default: stub('EmailMultiSelect'),
}))
vi.mock('@/components/Modals/EmailTemplateSelectorModal.vue', () => ({
  default: stub('EmailTemplateSelectorModal'),
}))
vi.mock('@/composables/useOwnProfile', () => ({
  useOwnProfile: () => reactive({ doc: { user_emails: S.accounts } }),
}))

const { default: EmailEditor } = await import('@/components/EmailEditor.vue')

const Button = defineComponent({ setup: () => () => h('button') })

function open(user = 'rep@mbp.example') {
  return mount(EmailEditor, {
    props: { modelValue: { name: 'CRM-DEAL-2026-00042' }, doctype: 'CRM Deal' },
    stubs: { Button },
    plugins: [{ install: (app) => app.provide('session', { user }) }],
  })
}

describe('EmailEditor', () => {
  beforeEach(() => {
    S.uploads.length = 0
    S.accounts = []
  })

  it("hides the FROM picker when the only mailbox is the rep's own address", () => {
    S.accounts = [{ email_account: 'Rep Mailbox', email_id: 'rep@mbp.example' }]
    const w = open()
    expect(w.el.textContent).not.toContain('FROM:')
  })

  it('offers the FROM picker when the rep has a shared mailbox', () => {
    S.accounts = [{ email_account: 'Sales', email_id: 'sales@mbp.example' }]
    const w = open()
    expect(w.el.textContent).toContain('FROM:')
  })

  it('uploads an inline image where the recipient can load it, under a name nobody can guess', async () => {
    open()
    const image = new File(['png'], 'image.png', { type: 'image/png' })
    await S.editor.uploadFunction(image)
    await S.editor.uploadFunction(image)

    const [first, second] = S.uploads
    // A private file is a 403 for the recipient's mail client.
    expect(first.options).toEqual({
      private: false,
      doctype: 'CRM Deal',
      docname: 'CRM-DEAL-2026-00042',
    })
    expect(first.file.name).toMatch(/^[0-9a-f]{24}-image\.png$/)
    expect(first.file.type).toBe('image/png')
    expect(second.file.name).not.toBe(first.file.name)
  })
})
