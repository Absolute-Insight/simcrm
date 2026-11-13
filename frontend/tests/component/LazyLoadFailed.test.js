import { describe, expect, it } from 'vitest'
import { mount } from './mount.js'
import LazyLoadFailed from '@/components/ui/LazyLoadFailed.vue'
import LazyTextEditorControl from '@/components/Controls/LazyTextEditorControl'

describe('LazyLoadFailed', () => {
  it('says what did not load and offers to try again', () => {
    const w = mount(LazyLoadFailed, {
      props: { what: 'the text editor', error: new Error('x') },
    })
    expect(w.el.querySelector('[role="alert"]').textContent).toContain(
      'Could not load the text editor',
    )
    ;[...w.el.querySelectorAll('button')]
      .find((b) => b.textContent.includes('Try again'))
      .click()
    expect(w.emitted.retry).toHaveLength(1)
  })

  it('sets its text in grey ink only', () => {
    const w = mount(LazyLoadFailed, { props: { what: 'the text editor' } })
    expect(w.el.innerHTML).not.toMatch(/text-ink-(green|red|orange|amber)-/)
    expect(w.el.innerHTML).toMatch(/text-ink-gray-[6-9]/)
  })
})

describe('LazyTextEditorControl', () => {
  it('is a component a form can render in place of the editor', () => {
    expect(LazyTextEditorControl.name).toBe('LazyComponent')
    expect(LazyTextEditorControl.inheritAttrs).toBe(false)
  })
})
