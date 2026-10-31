import { defineComponent, h, reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// Live Combobox instances in render order; the last one is "Add Field".
const comboboxes = []

vi.mock('frappe-ui', () => ({
  Combobox: defineComponent({
    props: { options: { type: Array, default: () => [] } },
    emits: ['update:selectedOption'],
    setup(props, { emit, slots }) {
      comboboxes.push({
        props,
        select: (o) => emit('update:selectedOption', o),
      })
      return () => h('div', slots.trigger?.({ open: false, setOpen() {} }))
    },
  }),
  Dialog: defineComponent({
    props: { open: Boolean },
    setup:
      (props, { slots }) =>
      () =>
        props.open ? h('div', [slots.default?.(), slots.actions?.()]) : null,
  }),
}))
vi.mock('vuedraggable', () => ({
  default: defineComponent({
    props: { list: { type: Array, default: () => [] } },
    setup:
      (props, { slots }) =>
      () =>
        h(
          'div',
          props.list.map((element) =>
            h('div', { class: 'card-field' }, slots.item({ element })),
          ),
        ),
  }),
}))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({
    getFields: () => [
      { fieldname: 'status', label: 'Status', fieldtype: 'Select' },
      { fieldname: 'organization', label: 'Organization', fieldtype: 'Link' },
      { fieldname: 'email', label: 'Email', fieldtype: 'Data' },
      { fieldname: 'mobile_no', label: 'Mobile No', fieldtype: 'Data' },
      { fieldname: 'territory', label: 'Territory', fieldtype: 'Link' },
    ],
  }),
}))

const { default: KanbanSettings } = await import(
  '@/components/Kanban/KanbanSettings.vue'
)

const Button = defineComponent({
  props: { label: { type: String, default: '' } },
  setup:
    (props, { attrs }) =>
    () =>
      h('button', { onClick: attrs.onClick }, props.label),
})

async function openSettings() {
  comboboxes.length = 0
  // the shape of CRM Deal's default kanban view
  const list = reactive({
    data: {
      column_field: 'status',
      title_field: 'organization',
      kanban_fields: '["email", "mobile_no"]',
    },
  })
  const w = mount(KanbanSettings, {
    props: { doctype: 'CRM Deal', modelValue: list },
    stubs: { Button },
  })
  ;[...w.el.querySelectorAll('button')]
    .find((b) => b.textContent === 'Kanban settings')
    .click()
  await w.nextTick()
  await w.nextTick()
  const cardFields = () =>
    [...w.el.querySelectorAll('.card-field')].map((n) => n.textContent.trim())
  return { w, list, cardFields, addField: () => comboboxes.at(-1) }
}

describe('KanbanSettings', () => {
  it('opens listing the card fields the view already has', async () => {
    const { cardFields, addField } = await openSettings()
    expect(cardFields()).toEqual(['Email', 'Mobile No'])
    const offered = addField().props.options.map((o) => o.fieldname)
    expect(offered).not.toContain('email')
    expect(offered).not.toContain('mobile_no')
    expect(offered).toContain('territory')
  })

  it('Add Field appends to the card fields, and Apply sends all of them', async () => {
    const { w, addField } = await openSettings()
    addField().select(
      addField().props.options.find((o) => o.fieldname === 'territory'),
    )
    await w.nextTick()
    ;[...w.el.querySelectorAll('button')]
      .find((b) => b.textContent === 'Apply')
      .click()
    await w.nextTick()
    await w.nextTick()
    expect(w.emitted.update.at(-1)[0]).toEqual({
      column_field: 'status',
      title_field: 'organization',
      kanban_fields: ['email', 'mobile_no', 'territory'],
    })
  })
})
