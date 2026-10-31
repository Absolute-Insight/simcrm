import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, reactive } from 'vue'
import { mount } from './mount.js'
import { toAllDayNotification } from '@/components/Calendar/utils'

// An event's reminders when the event is switched to All Day. Audit FE-36:
// the conversion ran while rendering, and only for rows on screen. "10
// minutes before" became 10 days (60 minutes, 60 days: past the 28-day cap),
// and a collapsed list kept minutes under a summary promising "at 8:00 am".

vi.mock('frappe-ui', async () => {
  const { defineComponent, h } = await import('vue')
  return { TimePicker: defineComponent({ setup: () => () => h('div') }) }
})

const { default: EventNotifications } = await import(
  '@/components/Calendar/EventNotifications.vue'
)

const passthrough = defineComponent({
  props: ['label'],
  emits: ['click'],
  setup:
    (p, { emit }) =>
    () =>
      h('div', { onClick: (e) => emit('click', e) }, p.label),
})

function reminders(rows, { expanded = false } = {}) {
  const props = reactive({ modelValue: rows, isAllDay: false })
  const Host = defineComponent({
    setup: () => () => h(EventNotifications, props),
  })
  const w = mount(Host, {
    stubs: { FormControl: passthrough, Button: passthrough },
  })
  const summary = () =>
    w.el.querySelector('.truncate .truncate').textContent.trim()
  return {
    ...w,
    props,
    summary,
    async expand() {
      if (!expanded) return
      w.el.querySelector('.cursor-pointer').click()
      await nextTick()
    },
  }
}

describe('EventNotifications: switching an event to All Day', () => {
  for (const expanded of [true, false]) {
    it(`a 10-minute reminder becomes 1 day before at 8:00 am (list ${
      expanded ? 'expanded' : 'collapsed'
    })`, async () => {
      const rows = [{ type: 'Notification', before: 10, interval: 'minutes' }]
      const r = reminders(rows, { expanded })
      await r.expand()
      expect(r.summary()).toBe('10 minutes before')

      r.props.isAllDay = true
      await nextTick()
      await nextTick()

      expect(rows[0]).toEqual({
        type: 'Notification',
        before: 1,
        interval: 'days',
        time: '08:00',
      })
      expect(r.summary()).toBe('1 day before at 8:00 am')
    })
  }

  it('does not change a timed reminder while the event stays timed', async () => {
    const rows = [{ type: 'Email', before: 2, interval: 'hours' }]
    const r = reminders(rows, { expanded: true })
    await r.expand()
    await nextTick()
    expect(rows[0]).toEqual({ type: 'Email', before: 2, interval: 'hours' })
  })
})

describe('toAllDayNotification', () => {
  const convert = (before, interval, time) =>
    toAllDayNotification({ type: 'Email', before, interval, time })

  it('rounds a lead time up to whole days', () => {
    expect(convert(60, 'minutes')).toMatchObject({ before: 1 })
    expect(convert(24, 'hours')).toMatchObject({ before: 1 })
    expect(convert(25, 'hours')).toMatchObject({ before: 2 })
  })

  it('clamps to the 28 days the picker allows', () => {
    expect(convert(3600, 'hours')).toMatchObject({
      before: 28,
      interval: 'days',
    })
  })

  it('keeps a days or weeks reminder, and its time of day', () => {
    expect(convert(2, 'weeks', '09:30')).toEqual({
      type: 'Email',
      before: 2,
      interval: 'weeks',
      time: '09:30',
    })
    expect(convert(3, 'days')).toMatchObject({ before: 3, time: '08:00' })
  })
})
