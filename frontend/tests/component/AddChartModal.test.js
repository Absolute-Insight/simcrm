/**
 * Adding a chart to the manager grid, and rendering one the server no longer
 * knows. Number Chart opens with no metric picked; Add used to send that empty
 * name, and the server's {error: "Invalid chart name"} reply (a 200, not an
 * HTTP error) was pushed into the grid as a blank panel. After Save,
 * get_dashboard returns data=None for it, and DashboardItem threw on every
 * render reading `item.data.tooltip`.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from './mount.js'

const net = vi.hoisted(() => ({ sent: [], reply: null, toasts: [] }))

vi.mock('frappe-ui', async (importOriginal) => {
  const actual = await importOriginal()
  const { defineComponent, h } = await import('vue')
  return {
    ...actual,
    Dialog: defineComponent({
      props: { open: Boolean, title: String },
      setup:
        (props, { slots }) =>
        () =>
          props.open ? h('div', [slots.default?.(), slots.actions?.()]) : null,
    }),
    FormControl: defineComponent({
      props: {
        modelValue: String,
        type: String,
        label: String,
        options: Array,
      },
      emits: ['update:modelValue'],
      setup:
        (props, { emit }) =>
        () =>
          h('select', {
            'data-label': props.label,
            onChange: (e) => emit('update:modelValue', e.target.value),
          }),
    }),
    toast: { error: (message) => net.toasts.push(message) },
    createResource: (options) => ({
      fetch() {
        net.sent.push(options.params)
        options.onSuccess(net.reply)
        return Promise.resolve(net.reply)
      },
    }),
  }
})
vi.mock('frappe-ui/experimental', async () => {
  const { defineComponent, h } = await import('vue')
  const chart = defineComponent({ render: () => h('i') })
  return { AxisChart: chart, DonutChart: chart, NumberChart: chart }
})

import AddChartModal from '@/components/Dashboard/AddChartModal.vue'
import DashboardItem from '@/components/Dashboard/DashboardItem.vue'

const Button = defineComponent({
  props: { label: String, disabled: Boolean, variant: String },
  emits: ['click'],
  setup:
    (props, { emit }) =>
    () =>
      h(
        'button',
        { disabled: props.disabled, onClick: () => emit('click') },
        props.label,
      ),
})

function openModal() {
  const items = ref([])
  const open = ref(true)
  const wrapper = mount(AddChartModal, {
    props: {
      modelValue: open,
      'onUpdate:modelValue': (v) => (open.value = v),
      items: items.value,
      'onUpdate:items': (v) => (items.value = v),
    },
    stubs: { Button },
  })
  const choose = async (label, value) => {
    const select = wrapper.el.querySelector(`[data-label="${label}"]`)
    select.innerHTML = `<option value="${value}">${value}</option>`
    select.value = value
    select.dispatchEvent(new Event('change'))
    await nextTick()
  }
  const add = () =>
    [...wrapper.el.querySelectorAll('button')].find(
      (b) => b.textContent === 'Add',
    )
  return { items, open, choose, add }
}

const flush = () => new Promise((r) => setTimeout(r, 0))

beforeEach(() => {
  Object.assign(net, { sent: [], reply: null, toasts: [] })
})

describe('AddChartModal', () => {
  it('will not add a number chart until a metric is picked', async () => {
    const modal = openModal()
    await modal.choose('Chart Type', 'number_chart')
    expect(modal.add().disabled).toBe(true)
    modal.add().click()
    await flush()
    expect(net.sent).toEqual([])
    expect(modal.items.value).toEqual([])

    net.reply = { title: 'Avg Deal Value', value: 5 }
    await modal.choose('Number Chart', 'average_deal_value')
    expect(modal.add().disabled).toBe(false)
    modal.add().click()
    await flush()
    expect(modal.items.value.map((i) => i.name)).toEqual(['average_deal_value'])
    expect(modal.open.value).toBe(false)
  })

  it("does not place the server's error reply in the grid as a chart", async () => {
    const modal = openModal()
    await modal.choose('Chart Type', 'axis_chart')
    net.reply = { error: 'Invalid chart name' }
    modal.add().click()
    await flush()
    expect(modal.items.value).toEqual([])
    expect(net.toasts).toEqual(['Invalid chart name'])
    expect(modal.open.value).toBe(true) // still there to pick another
  })
})

describe('DashboardItem', () => {
  it('renders a saved number chart that came back with no data', async () => {
    const errors = []
    mount(DashboardItem, {
      props: {
        index: 0,
        item: {
          name: '',
          type: 'number_chart',
          layout: { x: 0, y: 0, w: 4, h: 2, i: '_ab12' },
          data: null,
        },
      },
      plugins: [(app) => (app.config.errorHandler = (e) => errors.push(e))],
    })
    await nextTick()
    expect(errors.map((e) => e.message)).toEqual([])
  })
})
