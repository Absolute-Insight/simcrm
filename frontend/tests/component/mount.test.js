import { defineComponent, h } from 'vue'
import { describe, expect, it } from 'vitest'
import { mount } from './mount.js'
import { Badge } from 'frappe-ui'

describe('component test harness', () => {
  it('mounts an SFC from the app and records its emits', async () => {
    const Probe = defineComponent({
      emits: ['picked'],
      props: { label: { type: String, default: '' } },
      setup(props, { emit }) {
        return () =>
          h('button', { onClick: () => emit('picked', props.label) }, [
            h(Badge, { label: props.label }),
          ])
      },
    })
    const w = mount(Probe, { props: { label: 'Open' } })
    w.el.querySelector('button').click()
    await w.nextTick()
    expect(w.el.textContent).toContain('Open')
    expect(w.emitted.picked).toEqual([['Open']])
    w.unmount()
  })
})
