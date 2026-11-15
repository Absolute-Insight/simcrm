import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { mount } from './mount.js'
import { flush } from './stubs.js'

// The editor's chunk: S.fetch decides what each attempt to load it does.
const S = vi.hoisted(() => ({ fetch: null, editors: [] }))

vi.mock('@/utils/lazyComponent', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    // the real helper, with the chunk fetch in the test's hands
    lazyComponent: (loader, options) =>
      actual.lazyComponent(() => S.fetch(), options),
  }
})

const { lazyTextEditor } = await import('@/components/Controls/LazyTextEditor')

const Editor = {
  name: 'TextEditor',
  props: ['content', 'placeholder', 'editorClass'],
  emits: ['change'],
  setup(props, { emit, expose }) {
    expose({ focus: () => 'focused' })
    S.editors.push({ props, type: (value) => emit('change', value) })
    return () => h('div', { class: 'the-editor' })
  },
}

beforeEach(() => {
  S.editors.length = 0
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

describe('LazyTextEditor', () => {
  it('hands the editor its props and listeners, and its ref what it exposes', async () => {
    S.fetch = async () => ({ default: Editor })
    const changes = []
    const w = mount(lazyTextEditor(), {
      props: {
        content: '<p>Regards</p>',
        placeholder: 'Type something...',
        editorClass: 'prose-sm',
        onChange: (value) => changes.push(value),
      },
    })
    // nothing in its place before it has loaded, and no ref to call into
    expect(w.vm.focus).toBeUndefined()
    await flush()

    expect(w.el.querySelector('.the-editor')).not.toBeNull()
    expect(S.editors[0].props).toMatchObject({
      content: '<p>Regards</p>',
      placeholder: 'Type something...',
      editorClass: 'prose-sm',
    })
    S.editors[0].type('<p>Kind regards</p>')
    expect(changes).toEqual(['<p>Kind regards</p>'])
    expect(w.vm.focus()).toBe('focused')
  })

  it('leaves a retry where the editor would be when it cannot be fetched', async () => {
    S.fetch = () =>
      Promise.reject(new Error('Failed to fetch dynamically imported module'))
    const w = mount(lazyTextEditor(), { props: { content: '' } })
    await flush()
    expect(w.el.querySelector('.the-editor')).toBeNull()
    expect(w.el.querySelector('[role="alert"]').textContent).toContain(
      'Could not load the text editor',
    )

    S.fetch = async () => ({ default: Editor })
    ;[...w.el.querySelectorAll('button')]
      .find((b) => b.textContent.includes('Try again'))
      .click()
    await flush()
    expect(w.el.querySelector('[role="alert"]')).toBeNull()
    expect(w.el.querySelector('.the-editor')).not.toBeNull()
  })
})
