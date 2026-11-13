import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick, reactive } from 'vue'

// The real useCRMCommands and useCommandPalette; only the server is a stub.
const S = vi.hoisted(() => ({ calls: [], answer: null }))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  call: vi.fn((method, args) => {
    S.calls.push({ method, query: args?.query })
    return Promise.resolve(S.answer(args?.query))
  }),
}))
vi.mock('vue-router', () => ({
  useRoute: () => reactive({ name: 'Home', params: {} }),
}))
vi.mock('@/router', () => ({ default: { push: vi.fn() } }))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@example.com' }),
}))
vi.mock('@/stores/assistant', () => ({
  assistantVisible: { value: false },
  toggleAssistant: () => {},
}))
vi.mock('@/composables/doctypeModal', () => ({
  useDoctypeModal: () => ({ showModal() {} }),
}))
vi.mock('@/composables/useNavLinks', () => ({
  useNavLinks: () => [{ key: 'leads', label: 'Leads', to: 'Leads' }],
}))
vi.mock('@/composables/settings', () => ({
  isMobileView: { value: false },
  showSettings: { value: false },
}))
vi.mock('@/utils', () => ({ prettyDate: () => '' }))

const { useCRMCommands } = await import(
  '@/components/CommandPalette/useCRMCommands'
)
const palette = await import('@/composables/useCommandPalette')

const DEBOUNCE = 250
const wait = (ms = 20) => new Promise((resolve) => setTimeout(resolve, ms))
const searches = () =>
  S.calls
    .filter((c) => c.method === 'crm.api.command_palette.search')
    .map((c) => c.query)
const lead = (title) => ({
  doctype: 'CRM Lead',
  name: title,
  title,
  route: 'Lead',
})
const titles = (group) =>
  palette.commandPaletteItems.value
    .filter((item) => item.group === group)
    .map((item) => item.title)

let app
beforeEach(async () => {
  app?.unmount()
  palette.closeCommandPalette()
  palette.commandPaletteQuery.value = ''
  await wait()
  S.answer = (query) => ({
    matches: query ? [lead(`${query} match`)] : [],
    recent: query ? [] : [lead('Recently opened')],
    upcoming: [],
  })
  app = createApp({
    setup() {
      useCRMCommands()
      return () => null
    },
  })
  app.mount(document.createElement('div'))
  await wait()
  S.calls.length = 0
})

describe('command palette search requests', () => {
  it('sends one search when the palette is opened again after a search', async () => {
    palette.openCommandPalette()
    palette.commandPaletteQuery.value = 'acme'
    await wait(DEBOUNCE)
    palette.closeCommandPalette() // the query stays as it was typed
    await wait()
    S.calls.length = 0

    palette.openCommandPalette() // empties the query and opens, in one tick
    await wait()

    expect(searches()).toEqual([''])
    // and the one answer is shown, not thrown away as superseded
    expect(titles('Recent')).toEqual(['Recently opened'])
    expect(palette.commandPaletteSearching.value).toBe(false)
  })

  it('sends one search on a first open', async () => {
    palette.openCommandPalette()
    await wait()
    expect(searches()).toEqual([''])
  })

  it('still searches what is typed, and the untyped list once it is cleared', async () => {
    palette.openCommandPalette()
    await wait()
    palette.commandPaletteQuery.value = 'acme'
    await wait(DEBOUNCE)
    expect(titles('Records')).toEqual(['acme match'])
    palette.commandPaletteQuery.value = ''
    await wait()
    expect(searches()).toEqual(['', 'acme', ''])
    expect(titles('Recent')).toEqual(['Recently opened'])
  })

  it('an answer that typing has overtaken is not shown, and is asked for again when the box is cleared', async () => {
    let release
    S.answer = (query) =>
      query
        ? { matches: [], recent: [], upcoming: [] }
        : new Promise((resolve) => (release = resolve))
    palette.openCommandPalette() // the untyped list is slow to come back
    await nextTick()
    palette.commandPaletteQuery.value = 'ac' // typing overtakes it
    await nextTick()
    S.answer = () => ({
      matches: [],
      recent: [lead('Fresh')],
      upcoming: [],
    })
    palette.commandPaletteQuery.value = '' // cleared before either came back
    await wait()
    release({ matches: [], recent: [lead('Stale')], upcoming: [] })
    await wait()
    expect(searches()).toEqual(['', ''])
    expect(titles('Recent')).toEqual(['Fresh'])
  })
})
