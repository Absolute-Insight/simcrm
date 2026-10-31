import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount } from './mount.js'

// EventModal, opened from a deal's or lead's Events tab. Audit FE-01: the
// event arrived without its child tables (useEvent never fetched them), the
// modal showed none, and Save sent both empty through set_value, which
// replaces a child table with what it is given.

const submitted = vi.hoisted(() => ({ setValue: [], insert: [] }))

const passthrough = (name) =>
  defineComponent({
    name,
    inheritAttrs: false,
    props: ['modelValue', 'label', 'disabled', 'loading', 'message'],
    emits: ['update:modelValue', 'click'],
    setup(props, { slots, emit }) {
      return () =>
        h(
          name === 'Button' ? 'button' : 'div',
          { 'data-stub': name, onClick: (e) => emit('click', e) },
          [props.label, slots.default?.()],
        )
    },
  })

vi.mock('frappe-ui', async () => {
  const { defineComponent, h } = await import('vue')
  const dayjs = (await import('dayjs')).default
  const stub = (name) =>
    defineComponent({
      name,
      props: ['modelValue', 'message', 'open'],
      setup:
        (_, { slots }) =>
        () =>
          h('div', { 'data-stub': name }, [
            slots.title?.(),
            slots['body-content']?.(),
            slots.default?.(),
            slots.actions?.(),
          ]),
    })
  const resource = () => ({
    data: null,
    update() {},
    reload: async () => [],
    setValue: {
      loading: false,
      submit: (values) => submitted.setValue.push(values),
    },
    insert: {
      loading: false,
      submit: (values) => submitted.insert.push(values),
    },
    delete: { submit() {} },
  })
  return {
    Dialog: stub('Dialog'),
    Switch: stub('Switch'),
    ErrorMessage: stub('ErrorMessage'),
    DatePicker: stub('DatePicker'),
    TimePicker: stub('TimePicker'),
    Dropdown: stub('Dropdown'),
    dayjs,
    createListResource: resource,
    call: vi.fn(),
  }
})
vi.mock('frappe-ui/experimental', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    TextEditor: defineComponent({ setup: () => () => h('div') }),
    CalendarColorMap: { green: { color: '#30A66D' } },
  }
})
vi.mock('@/components/Calendar/Attendee.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent({ setup: () => () => h('div') }) }
})
vi.mock('@/components/Calendar/EventNotifications.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent({ setup: () => () => h('div') }) }
})
vi.mock('@/stores/global', () => ({ globalStore: () => ({ $dialog() {} }) }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (u) => ({ full_name: u, user_image: '' }) }),
}))

const { default: EventModal } = await import(
  '@/components/Modals/EventModal.vue'
)

const TextInput = defineComponent({
  name: 'TextInput',
  props: ['modelValue'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () =>
      h('input', {
        value: props.modelValue,
        onInput: (e) => emit('update:modelValue', e.target.value),
      })
  },
})

const flush = async () => {
  for (let i = 0; i < 5; i++) {
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))
  }
}

async function editTitleAndSave(event) {
  const w = mount(EventModal, {
    props: {
      modelValue: true,
      event,
      doctype: 'CRM Deal',
      docname: 'CRM-DEAL-1',
    },
    stubs: {
      TextInput,
      Button: passthrough('Button'),
      FormControl: passthrough('FormControl'),
    },
  })
  await flush()
  const title = w.el.querySelector('input')
  title.value = 'Visit: Impala Springs (moved)'
  title.dispatchEvent(new Event('input'))
  await flush()
  const save = [...w.el.querySelectorAll('button')].find(
    (b) => b.textContent === 'Update',
  )
  save.click()
  await flush()
  return submitted.setValue.at(-1)
}

const visit = {
  name: 'EV-1',
  subject: 'Visit: Impala Springs',
  starts_on: '2026-10-30 09:00:00',
  ends_on: '2026-10-30 10:00:00',
  all_day: 0,
  event_type: 'Private',
  owner: { label: 'Rep', name: 'rep@mbp.test' },
}

beforeEach(() => {
  submitted.setValue.length = 0
  submitted.insert.length = 0
})

describe('EventModal: saving an edit from the Events tab', () => {
  it('leaves out child tables the event arrived without', async () => {
    const saved = await editTitleAndSave({ ...visit })
    expect(saved.subject).toBe('Visit: Impala Springs (moved)')
    expect(saved).not.toHaveProperty('event_participants')
    expect(saved).not.toHaveProperty('notifications')
  })

  it('saves the loaded child tables back as they were', async () => {
    const participants = [
      {
        name: 'p-org',
        reference_doctype: 'CRM Organization',
        reference_docname: 'Impala Springs',
        email: null,
      },
      {
        name: 'p-buyer',
        reference_doctype: 'Contact',
        reference_docname: 'C-1',
        email: 'buyer@client.test',
        attending: 'Yes',
      },
    ]
    const notifications = [
      { name: 'n1', type: 'Email', before: 10, interval: 'minutes' },
    ]
    const saved = await editTitleAndSave({
      ...visit,
      event_participants: participants,
      notifications,
    })
    expect(saved.event_participants).toEqual(participants)
    expect(saved.notifications).toEqual(notifications)
  })
})
