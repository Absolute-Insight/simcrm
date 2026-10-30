import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'
import { translation } from './stubs.js'
import GlobalModals from '@/components/Modals/GlobalModals.vue'
import {
  activeHelpArticle,
  helpCenterVisible,
  helpContent,
  openHelpCenter,
} from '@/stores/help'
import { mentorOpen } from '@/stores/mentor'

// The real GlobalModals, HelpCenterModal and help/mentor stores. The sibling
// modals and the Mentor's chat are reduced to nothing.
vi.mock('frappe-ui', async (importOriginal) => {
  const { Dialog } = await import('./stubs.js')
  return { ...(await importOriginal()), Dialog }
})
const { none } = vi.hoisted(() => ({
  none: { default: { render: () => null } },
}))
vi.mock('@/components/CommandPalette/CommandPalette.vue', () => none)
vi.mock('@/components/Modals/FieldLayoutDialogContainer.vue', () => none)
vi.mock('@/components/Modals/ChangePasswordModal.vue', () => none)
vi.mock('@/components/Modals/CreateDocumentModal.vue', () => none)
vi.mock('@/components/Modals/QuickEntryModal.vue', () => none)
vi.mock('@/components/Modals/AboutModal.vue', () => none)
vi.mock('@/components/AgentChat.vue', () => none)

helpContent.data = {
  categories: ['Start', 'Settings'],
  articles: [
    {
      name: 'welcome',
      title: 'Welcome',
      category: 'Start',
      content: 'WELCOME',
    },
    {
      name: 'integrations',
      title: 'Integrations',
      category: 'Settings',
      content: 'INTEGRATIONS',
    },
  ],
}
helpContent.fetched = true

function shell() {
  const w = mount(GlobalModals, { plugins: [translation] })
  // The list column; below md it carries 'hidden md:flex' on the article pane.
  const nav = () => w.el.querySelector('.stub-Dialog > div > div')
  return { ...w, nav }
}

afterEach(async () => {
  helpCenterVisible.value = false
  activeHelpArticle.value = null
  mentorOpen.value = false
  await nextTick()
})

describe('Help Center opened from the app shell', () => {
  it('a help link opens on its article, not on a Mentor left open last time', async () => {
    const w = shell()
    openHelpCenter()
    await nextTick()
    w.el.querySelector('button[aria-label="Ask the Mentor"]').click()
    await nextTick()
    expect(mentorOpen.value).toBe(true)
    helpCenterVisible.value = false // closed
    await nextTick()

    openHelpCenter('integrations') // Settings -> a help link
    await nextTick()
    expect(mentorOpen.value).toBe(false)
    expect(w.el.textContent).toContain('INTEGRATIONS')
  })

  it('on a phone, an open that arrives with an article lands on the article', async () => {
    const w = shell()
    openHelpCenter('integrations')
    await nextTick()
    expect(w.nav().className).toContain('hidden md:flex')
  })

  it('a plain open lands on the list', async () => {
    const w = shell()
    openHelpCenter()
    await nextTick()
    expect(w.nav().className).not.toContain('hidden')
  })

  // The modal stays mounted between opens, so each open must pick its pane
  // from what it asks for, not from the article the last session ended on.
  it('on a phone, a repeat open of the same help link lands on the article again', async () => {
    const w = shell()
    openHelpCenter('integrations')
    await nextTick()
    helpCenterVisible.value = false
    await nextTick()

    openHelpCenter('integrations')
    await nextTick()
    expect(w.nav().className).toContain('hidden md:flex')
  })

  it('on a phone, a plain open after reading an article lands on the list', async () => {
    const w = shell()
    openHelpCenter()
    await nextTick()
    ;[...w.nav().querySelectorAll('button')]
      .find((b) => b.textContent.includes('Integrations'))
      .click()
    await nextTick()
    expect(w.nav().className).toContain('hidden md:flex')
    helpCenterVisible.value = false
    await nextTick()

    openHelpCenter()
    await nextTick()
    expect(w.nav().className).not.toContain('hidden')
  })

  it('a fresh open drops the search left from the last one', async () => {
    const w = shell()
    openHelpCenter()
    await nextTick()
    const input = w.el.querySelector('input')
    input.value = 'integ'
    input.dispatchEvent(new Event('input'))
    await nextTick()
    helpCenterVisible.value = false
    await nextTick()

    openHelpCenter()
    await nextTick()
    expect(w.el.querySelector('input').value).toBe('')
  })
})
