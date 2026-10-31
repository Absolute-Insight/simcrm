import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { mount } from './mount.js'
import StatTile from '@/components/Dashboard/StatTile.vue'
import ErrorState from '@/components/ui/ErrorState.vue'

describe('component test harness', () => {
  it('mounts an app SFC and records its emits alongside a handler from props', async () => {
    const onDrill = vi.fn()
    const w = mount(StatTile, {
      props: {
        label: 'Open deals',
        value: 7,
        drilldownLabel: 'Open deals',
        onDrill,
      },
    })
    await w.nextTick()
    expect(w.el.textContent).toContain('Open deals')
    w.el.querySelector('button')?.click()
    expect(w.emitted.drill).toHaveLength(1)
    expect(onDrill).toHaveBeenCalledOnce()
  })

  it('resolves ~icons/lucide imports and gives templates __()', async () => {
    const w = mount(ErrorState, { props: { title: 'Nothing here' } })
    await w.nextTick()
    expect(w.el.textContent).toContain('Nothing here')
  })

  it('captures a kebab-case emit and runs array handlers from props', () => {
    const one = vi.fn()
    const two = vi.fn()
    const Probe = {
      emits: ['update-value'],
      setup:
        (_, { emit }) =>
        () =>
          h('button', { onClick: () => emit('update-value', 1) }),
    }
    const w = mount(Probe, { props: { onUpdateValue: [one, two] } })
    w.el.querySelector('button').click()
    expect(w.emitted['update-value']).toEqual([[1]])
    expect(one).toHaveBeenCalledOnce()
    expect(two).toHaveBeenCalledOnce()
  })

  it('removes its container when the component throws on mount', () => {
    const Broken = {
      setup() {
        throw new Error('boom')
      },
    }
    expect(() => mount(Broken)).toThrow('boom')
    expect(document.body.children).toHaveLength(0)
  })

  it('cleans up after a test that did not unmount', () => {
    expect(document.body.children).toHaveLength(0)
  })
})
