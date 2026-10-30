import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createApp, defineComponent, h, nextTick, ref } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'

/* Node's own `localStorage` global (undefined without --localstorage-file)
   shadows happy-dom's, and useStorage reads it; give the test a real one. */
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
for (const target of new Set([globalThis, window])) {
  Object.defineProperty(target, 'localStorage', {
    configurable: true,
    value: storage,
  })
}

const { useActiveTabManager } = await import(
  '@/composables/useActiveTabManager'
)

const DEAL_TABS = [
  { name: 'Activity', value: 'activity' },
  { name: 'Emails', value: 'emails' },
  { name: 'Comments', value: 'comments' },
  { name: 'Data', value: 'data' },
]

let app
afterEach(() => app?.unmount())
beforeEach(() => storage.clear())

async function openDeal(hash, tabs = DEAL_TABS) {
  const state = {}
  const DealPage = defineComponent({
    setup() {
      Object.assign(state, useActiveTabManager(ref(tabs), 'lastDealTab'))
      return () => h('div')
    },
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/deals/:dealId', name: 'Deal', component: DealPage }],
  })
  router.push({ name: 'Deal', params: { dealId: 'CRM-DEAL-1' }, hash })
  await router.isReady()
  app = createApp(RouterView).use(router)
  app.mount(document.createElement('div'))
  await nextTick()
  return { router, state }
}

describe('useActiveTabManager', () => {
  it('opens the tab the hash names', async () => {
    storage.setItem('lastDealTab', 'emails')
    const { state } = await openDeal('#data')
    expect(state.tabIndex.value).toBe('data')
  })

  it('a comment anchor opens the activity feed, not the last-used tab', async () => {
    // A mention notification links to `#<Comment name>`. That matched no tab,
    // so the rep's last tab won, and Emails has no comment to scroll to.
    storage.setItem('lastDealTab', 'emails')
    const { router, state } = await openDeal('#8f3k2l9qpa')
    expect(state.tabIndex.value).toBe('activity')
    // the anchor survives for Activities to scroll to
    expect(router.currentRoute.value.hash).toBe('#8f3k2l9qpa')
    // and an anchor is not a tab worth remembering
    await new Promise((r) => setTimeout(r, 350))
    expect(storage.getItem('lastDealTab')).toBe('emails')
  })

  it('falls back to Comments when a page has no Activity tab', async () => {
    const { state } = await openDeal('#8f3k2l9qpa', DEAL_TABS.slice(1))
    expect(state.tabIndex.value).toBe('comments')
  })

  it('a comment anchor arriving on an open page switches to the feed', async () => {
    storage.setItem('lastDealTab', 'emails')
    const { router, state } = await openDeal('#emails')
    expect(state.tabIndex.value).toBe('emails')
    await router.push({ ...router.currentRoute.value, hash: '#8f3k2l9qpa' })
    await nextTick()
    expect(state.tabIndex.value).toBe('activity')
    await nextTick()
    expect(router.currentRoute.value.hash).toBe('#8f3k2l9qpa')

    // clicking another tab from there still records it
    state.tabIndex.value = 'data'
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))
    expect(router.currentRoute.value.hash).toBe('#data')
  })

  it('with no hash, reopens the last-used tab', async () => {
    storage.setItem('lastDealTab', 'emails')
    const { state } = await openDeal('')
    expect(state.tabIndex.value).toBe('emails')
  })
})
