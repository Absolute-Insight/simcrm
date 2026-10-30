import { describe, expect, it } from 'vitest'
import { h, nextTick } from 'vue'
import { mount } from './mount.js'
import Icon from '@/components/Icon.vue'
import { ensureLucideSprite, lucideSpriteReady } from '@/utils/lucideSprite'

/**
 * The lucide sprite used to be injected on every boot by frappe-ui's
 * spritePlugin, from the entry chunk. It now loads the first time a string
 * icon is drawn from it, and not before.
 */
const settle = async () => {
  for (let i = 0; i < 5; i++) {
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()
  }
}
const sprite = () => document.getElementById('lucide-sprite')

describe('Icon and the lucide sprite', () => {
  it('a component or emoji icon does not load the sprite', async () => {
    mount(Icon, { props: { icon: { render: () => h('i', 'x') } } })
    mount(Icon, { props: { icon: '🚀' } })
    await settle()
    expect(sprite()).toBeNull()
    expect(lucideSpriteReady.value).toBe(false)
  })

  it('a string icon loads the sprite once, and draws from it', async () => {
    const first = mount(Icon, { props: { icon: 'lucide-zap' } })
    mount(Icon, { props: { icon: 'phone' } })
    await ensureLucideSprite()
    await settle()

    expect(document.querySelectorAll('#lucide-sprite')).toHaveLength(1)
    expect(sprite().querySelector('symbol#zap')).not.toBeNull()
    expect(lucideSpriteReady.value).toBe(true)
    expect(first.el.querySelector('use').getAttribute('href')).toBe('#zap')
  })
})
