import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from './mount.js'

// frappe-ui's Button renders a component iconLeft as given and a lucide-*
// string as a class; the stub does the same so the test sees what it would.
vi.mock('frappe-ui', () => ({
  Button: defineComponent({
    props: {
      label: { type: String, default: '' },
      iconLeft: { type: [String, Object, Function], default: null },
    },
    setup: (props) => () =>
      h('button', [
        !props.iconLeft
          ? null
          : typeof props.iconLeft === 'string'
            ? h('span', { class: props.iconLeft })
            : h(props.iconLeft, { class: 'size-4' }),
        props.label,
      ]),
  }),
}))

const ButtonControl = (await import('@/components/Controls/ButtonControl.vue'))
  .default

describe('ButtonControl', () => {
  it('renders the icon a Button field is given', () => {
    const w = mount(ButtonControl, {
      props: { label: 'Call', icon: 'lucide-phone' },
    })
    // From the sprite main.js installs: Tailwind only writes a lucide-* class
    // for a name it finds in the source, and this one is set at runtime.
    const use = w.el.querySelector('button svg use')
    expect(use?.getAttribute('href')).toBe('#phone')
    expect(use.parentNode.getAttribute('class')).toContain('size-4')
    w.unmount()
  })

  it('renders no icon when none is set', () => {
    const w = mount(ButtonControl, { props: { label: 'Call' } })
    expect(w.el.querySelector('button svg, button span')).toBeNull()
    expect(w.el.textContent).toBe('Call')
    w.unmount()
  })
})
