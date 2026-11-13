import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'

// 13 Nov 2026 in Africa/Johannesburg (+02:00), set through a fake clock so the
// times here do not depend on the machine's zone.
const S = vi.hoisted(() => ({ dropdown: null }))

vi.mock('frappe-ui', async (importOriginal) => {
  const { h } = await import('vue')
  const real = await importOriginal()
  real.setConfig('localTimezone', 'Africa/Johannesburg')
  real.setConfig('systemTimezone', 'Africa/Johannesburg')
  return {
    ...real,
    // The real menu opens through a reka popover; this one opens when told.
    Dropdown: {
      name: 'Dropdown',
      props: ['options'],
      emits: ['update:open'],
      mounted() {
        S.dropdown = this
      },
      render() {
        return h('div', this.$slots.default?.())
      },
    },
    Dialog: {
      name: 'Dialog',
      props: ['actions', 'open'],
      render() {
        return h('div', [
          this.$slots.default?.(),
          h('button', {
            'data-action': 'schedule',
            disabled: this.actions[0].disabled,
          }),
        ])
      },
    },
    DateTimePicker: { name: 'DateTimePicker', render: () => null },
    ErrorMessage: {
      name: 'ErrorMessage',
      props: ['message'],
      render() {
        return h('p', { 'data-error': '' }, this.message)
      },
    },
  }
})

const { default: ScheduleSendButton } = await import(
  '@/components/ScheduleSendButton.vue'
)

const at = (utc) => vi.setSystemTime(new Date(utc))
const todaySlots = () =>
  (S.dropdown.options.find((g) => g.group === 'Today')?.options ?? []).map(
    (o) => o.label,
  )

async function open() {
  const w = mount(ScheduleSendButton, {
    stubs: { Button: { render: () => null } },
  })
  await nextTick()
  return w
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  at('2026-11-13T06:00:00Z') // 08:00 local: the composer mounts with the page
})
afterEach(() => vi.useRealTimers())

describe('ScheduleSendButton menu', () => {
  it('opened from the keyboard hours after the page loaded offers only what is left of today', async () => {
    await open()
    expect(todaySlots()).toEqual(['Morning', 'Afternoon', 'Evening'])
    at('2026-11-13T12:00:00Z') // 14:00 local
    S.dropdown.$emit('update:open', true) // Enter on the chevron: no pointerdown
    await nextTick()
    expect(todaySlots()).toEqual(['Evening'])
  })

  it('opened after midnight, "Tomorrow" is the day after the new day', async () => {
    const w = await open()
    at('2026-11-13T23:30:00Z') // 01:30 local on the 14th
    S.dropdown.$emit('update:open', true)
    await nextTick()
    S.dropdown.options.find((g) => g.group === 'Tomorrow').options[0].onClick()
    expect(w.emitted.schedule[0][0]).toBe('2026-11-15 09:00:00')
  })

  it('closing the menu does not move its clock', async () => {
    await open()
    S.dropdown.$emit('update:open', true)
    at('2026-11-13T12:00:00Z')
    S.dropdown.$emit('update:open', false)
    await nextTick()
    expect(todaySlots()).toEqual(['Morning', 'Afternoon', 'Evening'])
  })
})

describe('ScheduleSendButton custom time', () => {
  it('a picked time that passed while the dialog sat open is refused, and says why', async () => {
    const w = await open()
    const m = w.vm.$.setupState
    m.pickedTime = '2026-11-13 08:10:00' // ten minutes ahead
    await nextTick()
    expect(m.pickedOk).toBe(true)
    at('2026-11-13T06:40:00Z') // 08:40 local
    m.schedulePicked()
    await nextTick()
    expect(w.emitted.schedule).toBeUndefined()
    expect(w.el.querySelector('[data-error]').textContent).toBe(
      'Pick a time in the future',
    )
    expect(w.el.querySelector('[data-action]').disabled).toBe(true)
  })

  it('a picked time still ahead is sent in the site timezone', async () => {
    const w = await open()
    const m = w.vm.$.setupState
    m.pickedTime = '2026-11-13 09:30:00'
    await nextTick()
    at('2026-11-13T06:40:00Z')
    m.schedulePicked()
    expect(w.emitted.schedule[0]).toEqual([
      '2026-11-13 09:30:00',
      'Fri, 13 Nov, 9:30 AM',
      true,
    ])
  })
})
