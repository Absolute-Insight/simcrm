import { defineComponent, h } from 'vue'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// Node's own localStorage global shadows happy-dom's and is not usable here,
// which would quietly turn useStorage into a per-instance ref. Give the window
// a real in-memory Storage so a shared key is observable.
const mem = new Map()
const storage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
  clear: () => mem.clear(),
  key: (i) => [...mem.keys()][i] ?? null,
  get length() {
    return mem.size
  },
}
beforeAll(() => {
  for (const target of [globalThis, window]) {
    Object.defineProperty(target, 'localStorage', {
      value: storage,
      configurable: true,
    })
  }
})
afterEach(() => storage.clear())

vi.mock('@/components/ListBulkActions.vue', () => ({
  default: defineComponent({ render: () => h('div') }),
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@example.com' }),
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {}, params: {} }) }))

const { ListView } = await import('frappe-ui/experimental')
const { default: ListRows } = await import(
  '@/components/ListViews/ListRows.vue'
)
const { default: DealsListView } = await import(
  '@/components/ListViews/DealsListView.vue'
)

const KEY = 'scrollPositionCRM Deal'
const columns = [{ label: 'Name', key: 'name' }]
const rows = (n) =>
  Array.from({ length: n }, (_, i) => ({ name: `CRM-DEAL-${i}` }))

function mountRows(props) {
  const list = rows(30)
  return mount(
    defineComponent({
      render: () =>
        h(
          ListView,
          { columns, rows: list, rowKey: 'name', options: {} },
          {
            default: () =>
              h(
                ListRows,
                { rows: list, doctype: 'CRM Deal', ...props },
                { default: ({ item }) => h('span', String(item)) },
              ),
          },
        ),
    }),
  )
}

async function scroll(w, top) {
  await w.nextTick()
  const scroller = w.el.querySelector('.v-list')
  scroller.scrollTop = top
  scroller.dispatchEvent(new Event('scroll'))
  await w.nextTick()
  return scroller
}

describe('ListRows scroll memory', () => {
  it("the doctype's main list remembers where it was", async () => {
    const main = mountRows()
    await scroll(main, 1500)
    expect(storage.getItem(KEY)).toBe('1500')
    main.unmount()

    const back = mountRows()
    await back.nextTick()
    expect(back.el.querySelector('.v-list').scrollTop).toBe(1500)
  })

  it('a list that opts out neither restores nor overwrites that position', async () => {
    storage.setItem(KEY, '1500')
    const embedded = mountRows({ scrollKey: '' })
    await embedded.nextTick()
    expect(embedded.el.querySelector('.v-list').scrollTop).toBe(0)
    await scroll(embedded, 300)
    expect(storage.getItem(KEY)).toBe('1500')
  })

  it("an organization's Deals tab does not share the Deals list's slot", async () => {
    storage.setItem(KEY, '1500')
    // how Organization.vue / Contact.vue embed it
    const tab = mount(DealsListView, {
      props: {
        rows: rows(20),
        columns,
        options: { selectable: false, showTooltip: false, scrollKey: '' },
      },
      stubs: { Button: { render: () => null } },
    })
    await tab.nextTick()
    expect(tab.el.querySelector('.v-list').scrollTop).toBe(0)
    await scroll(tab, 300)
    expect(storage.getItem(KEY)).toBe('1500')
  })
})
