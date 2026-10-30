import { describe, expect, it, vi } from 'vitest'
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

  it('cleans up after a test that did not unmount', () => {
    expect(document.body.children).toHaveLength(0)
  })
})
