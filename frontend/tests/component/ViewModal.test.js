import { defineComponent, h, nextTick, reactive, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

const { call } = vi.hoisted(() => ({ call: vi.fn(() => Promise.resolve({})) }))
vi.mock('frappe-ui', () => ({ call }))
vi.mock('frappe-ui/experimental', () => ({
  IconPicker: { render: () => null },
}))
vi.mock('@/utils', () => ({ isEmoji: () => false }))

const { default: ViewModal } = await import('@/components/Modals/ViewModal.vue')

let dismiss
const Dialog = defineComponent({
  props: { open: Boolean },
  emits: ['update:open'],
  setup(props, { emit, slots }) {
    dismiss = () => emit('update:open', false) // Esc, the overlay, the X
    return () =>
      props.open ? h('div', [slots.default?.(), slots.actions?.()]) : null
  },
})
const FormControl = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  setup:
    (props, { emit }) =>
    () =>
      h('input', {
        value: props.modelValue,
        onInput: (e) => emit('update:modelValue', e.target.value),
      }),
})
const Button = defineComponent({
  props: { label: { type: String, default: '' } },
  setup:
    (props, { attrs }) =>
    () =>
      h('button', { onClick: attrs.onClick }, props.label),
})

function openWith(view, options = {}) {
  call.mockClear()
  const open = ref(false)
  const current = ref({})
  const Host = defineComponent({
    setup: () => () =>
      h(ViewModal, {
        modelValue: open.value,
        'onUpdate:modelValue': (v) => (open.value = v),
        view: current.value,
        'onUpdate:view': (v) => (current.value = v),
        doctype: 'CRM Deal',
        options,
      }),
  })
  const w = mount(Host, { stubs: { Dialog, FormControl, Button } })
  current.value = view
  open.value = true
  return { w, open }
}

async function rename(w, label) {
  await nextTick()
  const input = w.el.querySelector('input')
  input.value = label
  input.dispatchEvent(new Event('input'))
  await nextTick()
}

describe('ViewModal', () => {
  it('a dismissed edit leaves the view it was given as it was', async () => {
    // a pinned view, as the views store holds it: the sidebar renders this
    const stored = reactive({ name: 7, label: 'My Open Deals', mode: 'edit' })
    const { w, open } = openWith(stored)
    await rename(w, 'Q4 pipeline')
    dismiss()
    await nextTick()

    expect(open.value).toBe(false)
    expect(call).not.toHaveBeenCalled()
    expect(stored.label).toBe('My Open Deals')
  })

  it('Save Changes sends the edited view and hands it to afterUpdate', async () => {
    const afterUpdate = vi.fn()
    const stored = reactive({ name: 7, label: 'My Open Deals', mode: 'edit' })
    const { w, open } = openWith(stored, { afterUpdate })
    await rename(w, 'Q4 pipeline')
    ;[...w.el.querySelectorAll('button')]
      .find((b) => b.textContent === 'Save Changes')
      .click()
    await nextTick()
    await nextTick()

    expect(call).toHaveBeenCalledWith(
      'crm.fcrm.doctype.crm_view_settings.crm_view_settings.update',
      {
        view: expect.objectContaining({
          name: 7,
          label: 'Q4 pipeline',
          doctype: 'CRM Deal',
        }),
      },
    )
    expect(afterUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'Q4 pipeline' }),
    )
    expect(open.value).toBe(false)
  })

  it('opens each time on the view it is given now', async () => {
    const { w } = openWith({ name: 8, label: 'First', mode: 'duplicate' })
    await nextTick()
    expect(w.el.querySelector('input').value).toBe('First')
    expect(w.el.textContent).toContain('Duplicate')
  })
})
