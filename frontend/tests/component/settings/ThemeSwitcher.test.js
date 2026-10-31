import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../mount.js'

const scheme = vi.hoisted(() => ({ set: [], current: null }))
vi.mock('frappe-ui', async (importOriginal) => {
  const { ref } = await import('vue')
  scheme.current = ref('dark')
  return {
    ...(await importOriginal()),
    useColorScheme: () => ({
      colorScheme: scheme.current,
      setColorScheme: (value) => {
        scheme.set.push(value)
        scheme.current.value = value
      },
    }),
  }
})

const { default: ThemeSwitcher } = await import(
  '@/components/Settings/ThemeSwitcher.vue'
)

const radios = (el) => [...el.querySelectorAll('[role="radio"]')]
const key = (target, name) =>
  target.dispatchEvent(
    new KeyboardEvent('keydown', { key: name, bubbles: true }),
  )

beforeEach(() => {
  scheme.set.length = 0
  scheme.current.value = 'dark'
})

describe('ThemeSwitcher', () => {
  it('is a radio group of three named, focusable options', async () => {
    const { el } = mount(ThemeSwitcher, { props: { name: 'Vectora' } })
    await Promise.resolve()
    expect(
      el.querySelector('[role="radiogroup"]').getAttribute('aria-label'),
    ).toBe('Theme')
    expect(radios(el).map((r) => r.tagName)).toEqual([
      'BUTTON',
      'BUTTON',
      'BUTTON',
    ])
    expect(radios(el).map((r) => r.getAttribute('aria-label'))).toEqual([
      'Light',
      'Dark',
      'System',
    ])
    expect(radios(el).map((r) => r.getAttribute('aria-checked'))).toEqual([
      'false',
      'true',
      'false',
    ])
    // Tab enters the group at the chosen theme
    expect(radios(el).map((r) => r.tabIndex)).toEqual([-1, 0, -1])
  })

  it('chooses with the arrow keys and moves focus with the choice', async () => {
    const { el } = mount(ThemeSwitcher)
    await Promise.resolve()
    const [light, dark, system] = radios(el)
    dark.focus()
    key(dark, 'ArrowRight')
    await Promise.resolve()
    expect(scheme.set).toEqual(['system'])
    expect(document.activeElement).toBe(system)
    expect(system.getAttribute('aria-checked')).toBe('true')

    key(system, 'ArrowRight') // wraps round
    await Promise.resolve()
    expect(scheme.set.at(-1)).toBe('light')
    expect(document.activeElement).toBe(light)

    key(light, 'ArrowLeft')
    await Promise.resolve()
    expect(scheme.set.at(-1)).toBe('system')
  })

  it('chooses an option a keyboard activates', async () => {
    const { el } = mount(ThemeSwitcher)
    await Promise.resolve()
    // Enter and Space on a native button arrive as a click
    radios(el)[0].click()
    expect(scheme.set).toEqual(['light'])
  })
})
