import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// Counts the afterEach hooks the router is holding and how many run.
const hooks = vi.hoisted(() => ({ live: 0, runs: 0 }))

vi.mock('@/router', async () => {
  const { createRouter, createMemoryHistory } = await import('vue-router')
  const Blank = { render: () => null }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: ['Dashboard', 'Leads', 'Deals'].map((name) => ({
      path: '/' + name.toLowerCase(),
      name,
      component: Blank,
    })),
  })
  const afterEach = router.afterEach.bind(router)
  router.afterEach = (fn) => {
    hooks.live += 1
    const remove = afterEach((...args) => {
      hooks.runs += 1
      return fn(...args)
    })
    return () => {
      hooks.live -= 1
      remove()
    }
  }
  return { default: router }
})

const { Stub, SlotStub } = vi.hoisted(() => ({
  Stub: {
    render() {
      return this.$slots.default?.()
    },
  },
  SlotStub: {
    props: ['label', 'hideLabel', 'opened'],
    render() {
      return [
        this.$slots.header?.({ opened: true, hide: true, toggle() {} }),
        this.$slots.default?.(),
      ]
    },
  },
}))
vi.mock('frappe-ui', () => ({
  call: vi.fn(),
  KeyboardShortcut: Stub,
  Sidebar: Stub,
  SidebarItem: Stub,
  SidebarLabel: Stub,
  Tooltip: Stub,
}))
vi.mock('@/components/Layouts/SidebarBrand.vue', () => ({ default: Stub }))
vi.mock('@/components/Layouts/SidebarUser.vue', () => ({ default: Stub }))
vi.mock('@/components/CollapsibleSection.vue', () => ({ default: SlotStub }))
vi.mock('@/components/Icon.vue', () => ({ default: Stub }))
vi.mock('@/components/Notifications.vue', () => ({ default: Stub }))
vi.mock('@/components/Suggestions.vue', () => ({ default: Stub }))
vi.mock('@/components/Assistant.vue', () => ({ default: Stub }))
vi.mock('@/components/Settings/Settings.vue', () => ({ default: Stub }))
vi.mock('@/components/OnboardingPanel.vue', () => ({ default: Stub }))
vi.mock('@/stores/assistant', async () => {
  const { ref } = await import('vue')
  return { assistantVisible: ref(false), toggleAssistant: () => {} }
})
vi.mock('@/stores/suggestions', async () => {
  const { ref } = await import('vue')
  return {
    suggestionsStore: () => ({ toggle() {} }),
    openCountUnavailable: ref(false),
    openSuggestionsCount: ref(0),
    suggestionsVisible: ref(false),
  }
})
vi.mock('@/stores/notifications', async () => {
  const { ref } = await import('vue')
  return {
    notificationsStore: () => ({ toggle() {} }),
    unreadCountUnavailable: ref(false),
    unreadNotificationsCount: ref(0),
    visible: ref(false),
  }
})
vi.mock('@/stores/access', () => ({
  accessStore: () => ({ canSee: () => true }),
}))
vi.mock('@/stores/views', () => ({
  viewsStore: () => ({ getPinnedViews: () => [], getPublicViews: () => [] }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: { promise: Promise.resolve() },
    isManager: () => false,
    isAdmin: () => false,
  }),
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@example.com' }),
}))
vi.mock('@/composables/settings', async () => {
  const { ref } = await import('vue')
  return {
    showSettings: ref(false),
    activeSettingsPage: ref(''),
    mobileSidebarOpened: ref(false),
  }
})
vi.mock('@/composables/modals', async () => {
  const { ref } = await import('vue')
  return { showChangePasswordModal: ref(false) }
})
vi.mock('@/composables/useBroadcast.js', () => ({
  useBroadcast: () => ({ send() {} }),
}))
vi.mock('@/composables/demoData', async () => {
  const { ref } = await import('vue')
  return {
    useDemoData: () => ({ clearDemoData() {}, isDemoDataCreated: ref(false) }),
  }
})

const { default: router } = await import('@/router')
const { default: AppSidebar } = await import(
  '@/components/Layouts/AppSidebar.vue'
)

describe('AppSidebar', () => {
  it('takes its router hook with it when it unmounts', async () => {
    await router.push('/dashboard')

    // The mobile drawer mounts a fresh sidebar on every open.
    for (let i = 0; i < 5; i++) {
      const w = mount(AppSidebar, {
        props: { mobile: true },
        plugins: [router],
        stubs: { Button: { render: () => h('button') } },
      })
      w.unmount()
    }

    hooks.runs = 0
    await router.push('/leads')
    expect(hooks.live).toBe(0)
    expect(hooks.runs).toBe(0)
  })
})
