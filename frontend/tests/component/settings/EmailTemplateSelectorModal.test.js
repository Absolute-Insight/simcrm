import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../mount.js'
import { Button, FormControl, field, flush } from './standIns.js'

const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) => {
  const { defineComponent, h } = await import('vue')
  // v-model:open, as the picker binds it
  const Dialog = defineComponent({
    props: { open: Boolean },
    setup:
      (props, { slots }) =>
      () =>
        props.open
          ? h('div', { 'data-stub': 'Dialog' }, slots.default?.())
          : null,
  })
  return (await import('./standIns.js')).frappeUi(importOriginal, backend, {
    Dialog,
  })
})
vi.mock('frappe-ui/experimental', () => ({
  TextEditor: { render: () => null },
}))
vi.mock('@/composables/useBroadcast', () => ({
  useBroadcast: () => ({ on() {}, send() {} }),
}))
const who = vi.hoisted(() => ({ admin: false }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ isAdmin: () => who.admin }),
}))

const { showSettings, activeSettingsPage } = await import(
  '@/composables/settings'
)
const { default: EmailTemplateSelectorModal } = await import(
  '@/components/Modals/EmailTemplateSelectorModal.vue'
)

let templates
beforeEach(() => {
  who.admin = false
  showSettings.value = false
  activeSettingsPage.value = ''
  backend.handlers = { 'frappe.client.get_list': () => templates }
})

function open(doctype) {
  // main.js registers Button and TextInput globally; the picker relies on it
  return mount(EmailTemplateSelectorModal, {
    props: { modelValue: true, doctype },
    stubs: { Button, TextInput: FormControl },
  })
}

describe('EmailTemplateSelectorModal', () => {
  it('offers Create only to someone the Templates settings page is shown to', async () => {
    templates = []
    const rep = open('CRM Lead')
    await flush()
    expect(field(rep.el, 'Create')).toBeNull()
    expect(field(rep.el, 'Create New')).toBeNull()
    expect(rep.el.textContent).toContain(
      'An administrator can add templates in Settings.',
    )
    rep.unmount()

    who.admin = true
    const admin = open('CRM Deal')
    await flush()
    expect(field(admin.el, 'Create')).not.toBeNull()
    field(admin.el, 'Create New').click()
    expect(showSettings.value).toBe(true)
    expect(activeSettingsPage.value).toBe('Templates')
  })
})
