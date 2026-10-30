import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { fakeBackend } from './fakeBackend.js'
import { flushPromises } from './flush.js'
import { mount } from './mount.js'

const { toast, upload } = vi.hoisted(() => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  upload: {},
}))
vi.mock('frappe-ui', async (importOriginal) => {
  const actual = await importOriginal()
  // the uploader's file picker is the browser's; the test hands it a file
  const FileUploader = defineComponent({
    emits: ['success'],
    setup(_, { slots, emit }) {
      upload.succeed = (file) => emit('success', file)
      return () =>
        h(
          'div',
          slots.default?.({
            openFileSelector() {},
            error: null,
            uploading: false,
          }),
        )
    },
  })
  return { ...actual, FileUploader, toast }
})
vi.mock('@/components/Modals/ChangePasswordModal.vue', () => ({
  default: { render: () => null },
}))

import { Button, ErrorMessage } from 'frappe-ui'
import ProfileSettings from '@/components/Settings/Profile/ProfileSettings.vue'

let backend, profile, saved
beforeEach(() => {
  profile = {
    name: 'thabo@mbp.example',
    email: 'thabo@mbp.example',
    first_name: 'Thabo',
    last_name: 'Nkosi',
    user_image: null,
    language: 'en',
    time_zone: 'Africa/Johannesburg',
    email_signature: '',
    user_emails: [],
  }
  saved = []
  backend = fakeBackend()
  backend.handlers['crm.api.user.get_profile'] = () => ({ ...profile })
  backend.handlers['crm.api.user.update_profile'] = ({ changes }) => {
    saved.push(changes)
    Object.assign(profile, changes)
    return { ...profile }
  }
  toast.error.mockReset()
})

async function openNameEditor() {
  const w = mount(ProfileSettings, { stubs: { Button, ErrorMessage } })
  await flushPromises()
  w.el.querySelector('button').click() // the pencil beside the name
  await flushPromises()
  return { w, input: w.el.querySelector('input') }
}

async function type(input, value) {
  input.value = value
  input.dispatchEvent(new Event('input'))
  await flushPromises(2)
}

function press(input, key) {
  input.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
}

describe('ProfileSettings name editor (FE-129)', () => {
  it('Esc discards the edit, so the next photo save does not carry it', async () => {
    const { w, input } = await openNameEditor()
    await type(input, 'Thabo Mokoena')
    press(input, 'Escape')
    await flushPromises()
    expect(w.el.textContent).toContain('Thabo Nkosi')
    expect(w.el.textContent).not.toContain('Mokoena')

    upload.succeed({ file_url: '/files/thabo.png' })
    await flushPromises()
    expect(saved).toEqual([{ user_image: '/files/thabo.png' }])
  })

  it('keeps the space while the surname is retyped one key at a time', async () => {
    const { input } = await openNameEditor()
    for (const value of ['Thabo Nkos', 'Thabo Nk', 'Thabo N', 'Thabo ']) {
      await type(input, value)
    }
    expect(input.value).toBe('Thabo ')
    for (const ch of 'Mokoena') await type(input, input.value + ch)
    press(input, 'Enter')
    await flushPromises()
    expect(saved).toEqual([{ last_name: 'Mokoena' }])
  })
})
