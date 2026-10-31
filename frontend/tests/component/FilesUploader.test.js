import { h, nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// Each upload is a promise the test settles, in whatever order it likes --
// the real XHRs finish in size order, not list order.
const S = vi.hoisted(() => ({ uploads: [], area: null, toasts: [] }))

vi.mock('frappe-ui', () => ({
  toast: { error: (m) => S.toasts.push(m) },
}))
vi.mock('@/composables/settings', async () => {
  const { ref } = await import('vue')
  return { isMobileView: ref(false) }
})
vi.mock('@/components/FilesUploader/FilesUploaderArea.vue', () => ({
  default: {
    props: { modelValue: { type: Array, default: () => [] } },
    emits: ['update:modelValue'],
    setup(props, { emit, expose }) {
      S.area = { props, emit }
      expose({
        showWebLink: false,
        showCamera: false,
        webLink: null,
        cameraImage: null,
      })
      return () => null
    },
  },
}))
vi.mock('@/components/FilesUploader/filesUploaderHandler', () => ({
  default: class {
    constructor() {
      this.listeners = {}
    }
    on(event, fn) {
      ;(this.listeners[event] ||= []).push(fn)
    }
    upload(file) {
      return new Promise((resolve, reject) => {
        S.uploads.push({ file, resolve, reject })
        this.listeners.start?.forEach((fn) => fn())
      })
    }
  },
}))

const { default: FilesUploader } = await import(
  '@/components/FilesUploader/FilesUploader.vue'
)

const Dialog = {
  render() {
    return [this.$slots.default?.(), this.$slots.actions?.()]
  },
}
const Button = {
  inheritAttrs: false,
  render() {
    return h('button', {
      'data-label': this.$attrs.label,
      'data-loading': String(Boolean(this.$attrs.loading)),
      onClick: this.$attrs.onClick,
    })
  },
}

const file = (name) => ({
  name,
  type: 'application/pdf',
  fileObj: { name },
  private: true,
})

async function settle() {
  for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r))
}

async function attach(names) {
  const state = { open: true, afters: [] }
  const w = mount(FilesUploader, {
    props: {
      modelValue: true,
      'onUpdate:modelValue': (v) => (state.open = v),
      doctype: 'CRM Deal',
      docname: 'CRM-DEAL-2026-00001',
      onAfter: (uploaded) => state.afters.push(uploaded.map((f) => f.file_url)),
    },
    stubs: { Dialog, Button },
  })
  S.area.emit('update:modelValue', names.map(file))
  await nextTick()
  w.el.querySelector('[data-label="Attach"]').click()
  await nextTick()
  const spinning = () =>
    w.el.querySelector('[data-label="Attach"]')?.dataset.loading === 'true'
  return { state, spinning }
}

describe('FilesUploader batch', () => {
  beforeEach(() => {
    S.uploads.length = 0
    S.toasts.length = 0
  })

  it('finishes when every upload is back, not when the last-listed one is', async () => {
    const { state } = await attach(['quote.pdf', 'photo.pdf'])
    expect(S.uploads).toHaveLength(2)

    // The small file, listed last, comes back first.
    S.uploads[1].resolve({ file_url: '/files/photo.pdf' })
    await settle()
    expect(state.afters).toEqual([])
    expect(state.open).toBe(true)

    S.uploads[0].resolve({ file_url: '/files/quote.pdf' })
    await settle()
    expect(state.afters).toEqual([['/files/quote.pdf', '/files/photo.pdf']])
    expect(state.open).toBe(false)
  })

  it('keeps a failed file listed with its error and reports the rest', async () => {
    const { state, spinning } = await attach(['a.pdf', 'b.pdf'])
    S.uploads[0].reject('File too large')
    S.uploads[1].resolve({ file_url: '/files/b.pdf' })
    await settle()

    expect(state.afters).toEqual([['/files/b.pdf']])
    expect(state.open).toBe(true)
    expect(spinning()).toBe(false)
    const listed = S.area.props.modelValue
    expect(listed.map((f) => f.name)).toEqual(['a.pdf'])
    expect(listed[0].errorMessage).toBe('File too large')
  })

  it('stops the spinner when the last-listed file fails', async () => {
    const { state, spinning } = await attach(['a.pdf', 'b.pdf'])
    S.uploads[0].resolve({ file_url: '/files/a.pdf' })
    S.uploads[1].reject('Server error')
    await settle()

    expect(spinning()).toBe(false)
    expect(state.afters).toEqual([['/files/a.pdf']])
  })

  it('stops the spinner when a single upload fails', async () => {
    const { state, spinning } = await attach(['a.pdf'])
    S.uploads[0].reject('Server error')
    await settle()

    expect(spinning()).toBe(false)
    expect(state.afters).toEqual([])
    expect(S.area.props.modelValue[0].errorMessage).toBe('Server error')
  })
})
