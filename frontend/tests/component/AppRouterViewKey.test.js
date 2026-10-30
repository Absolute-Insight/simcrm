import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { mount } from './mount.js'

/**
 * App.vue keyed the page's <router-view> on `$route.fullPath`, hash included,
 * and the record pages record their active tab as the hash. So every tab
 * click on a Deal or Lead unmounted and remounted the whole page: the side
 * panel blanked and refetched, its open and scroll state reset, and the form
 * script's onRender ran again.
 */
const { Slot, Empty } = vi.hoisted(() => ({
  Slot: {
    render() {
      return this.$slots.default?.()
    },
  },
  Empty: { render: () => null },
}))
vi.mock('@/pages/NotPermitted.vue', () => ({ default: Empty }))
vi.mock('@/components/EventNotificationPopup.vue', () => ({ default: Empty }))
vi.mock('@/components/Modals/DoctypeModals.vue', () => ({ default: Empty }))
// defineAsyncComponent reads `__esModule` off the namespace it is handed
vi.mock('@/components/Layouts/DesktopLayout.vue', () => ({
  __esModule: true,
  default: Slot,
}))
vi.mock('@/components/Layouts/MobileLayout.vue', () => ({
  __esModule: true,
  default: Slot,
}))
vi.mock('@/utils/dialogs', () => ({ Dialogs: Empty }))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ isLoggedIn: true }),
}))
vi.mock('frappe-ui', () => ({ FrappeUIProvider: Slot, setConfig: () => {} }))

import App from '@/App.vue'

const settle = async () => {
  for (let i = 0; i < 5; i++) {
    await nextTick()
    await new Promise((r) => setTimeout(r, 5))
  }
}

async function mountApp() {
  let setups = 0
  const DealPage = defineComponent({
    props: { dealId: { type: String, default: '' } },
    setup(props) {
      setups++ // Deal.vue's setup: useDocument, the side panel, ...
      const tab = ref('activity')
      return () => h('div', `${props.dealId} ${tab.value}`)
    },
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/deals/:dealId',
        name: 'Deal',
        component: DealPage,
        props: true,
      },
    ],
  })
  router.push('/deals/CRM-DEAL-1#activity')
  await router.isReady()
  const wrapper = mount(App, { plugins: [router] })
  await settle()
  return { router, wrapper, setups: () => setups }
}

describe('the page router-view', () => {
  it('survives a tab change, which only changes the hash', async () => {
    const { router, setups } = await mountApp()
    expect(setups()).toBe(1)

    await router.push('/deals/CRM-DEAL-1#emails')
    await settle()
    await router.push('/deals/CRM-DEAL-1#notes')
    await settle()

    expect(router.currentRoute.value.hash).toBe('#notes')
    expect(setups()).toBe(1)
  })

  it('still remounts for another record', async () => {
    const { router, wrapper, setups } = await mountApp()
    await router.push('/deals/CRM-DEAL-2#activity')
    await settle()

    expect(setups()).toBe(2)
    expect(wrapper.el.textContent).toContain('CRM-DEAL-2')
  })
})
