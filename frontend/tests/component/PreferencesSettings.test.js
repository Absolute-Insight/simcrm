import { describe, it, expect, vi } from 'vitest'
import { fakeBackend, frappeError } from './fakeBackend.js'
import { collectRejections, flushPromises } from './flush.js'
import { mount } from './mount.js'
import { buttonByText, memoryStorage, setValue } from './stubs.js'

const { toast } = vi.hoisted(() => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('frappe-ui', async (importOriginal) => {
  const { Select } = await import('./stubs.js')
  return { ...(await importOriginal()), Combobox: Select, toast }
})
vi.mock('@/components/Controls/Link.vue', () => ({
  default: { render: () => null },
}))
// the brand store fetches FCRM Settings when it is imported
vi.mock('@/stores/settings', () => ({ getSettings: () => ({ brand: {} }) }))

import { Button } from 'frappe-ui'
import PreferencesSettings from '@/components/Settings/PreferencesSettings.vue'

vi.stubGlobal('localStorage', memoryStorage())

describe('PreferencesSettings save error (FE-132)', () => {
  it("toasts the server's reason, not the endpoint and exception class", async () => {
    const backend = fakeBackend()
    const refusal = frappeError(
      'Time Zone Mars/Olympus is not valid',
      'crm.api.user.update_profile',
    )
    backend.handlers['crm.api.user.get_profile'] = () => ({
      name: 'thabo@mbp.example',
      language: 'en',
      time_zone: 'Africa/Johannesburg',
    })
    backend.handlers['frappe.core.doctype.user.user.get_timezones'] = () => ({
      timezones: ['Africa/Johannesburg', 'Mars/Olympus'],
    })
    backend.handlers['crm.api.user.update_profile'] = () => {
      throw refusal
    }
    const w = mount(PreferencesSettings, { stubs: { Button } })
    await flushPromises()
    setValue(w.el.querySelector('select'), 'Mars/Olympus')
    await flushPromises()

    const rejections = await collectRejections(() =>
      buttonByText(w.el, 'Save').click(),
    )
    expect(toast.error).toHaveBeenCalledWith(
      'Time Zone Mars/Olympus is not valid',
    )
    expect(rejections.filter((r) => r !== refusal)).toEqual([])
  })
})
