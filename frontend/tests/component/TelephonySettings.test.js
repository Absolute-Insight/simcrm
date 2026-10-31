import { expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'
import { Button, formControls, setConfig } from './telephony/frappeUi.js'

vi.mock('frappe-ui', () => import('./telephony/frappeUi.js'))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    getUser: () => ({ name: 'rep@example.com' }),
    isManager: () => false,
  }),
}))
vi.mock('@/utils', () => ({ validatePhone: () => true }))
vi.mock('@/components/ui/ToneBadge.vue', () => ({
  default: { render: () => null },
}))

const flush = async (rounds = 4) => {
  for (let i = 0; i < rounds; i++) {
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

const agent = {
  name: 'rep@example.com',
  default_medium: 'Twilio',
  twilio_number: null,
  exotel_number: null,
  mobile_no: null,
}

// Set before the telephony composable loads, since it asks as soon as it is
// imported.
setConfig('resourceFetcher', async ({ url, params }) => {
  if (url.endsWith('is_call_integration_enabled')) {
    // both on, and this rep's saved default is Twilio
    return {
      integrations: { twilio: true, exotel: true },
      default_calling_medium: 'Twilio',
    }
  }
  if (url === 'frappe.client.get_value') return agent
  if (url === 'frappe.client.set_value')
    return { ...agent, ...params.fieldname }
  return {}
})
const telephony = await import('@/composables/telephony')
const { default: TelephonySettings } = await import(
  '@/components/Settings/Telephony/TelephonySettings.vue'
)

it('a saved Default Medium is the medium the next call goes out through', async () => {
  const w = mount(TelephonySettings, { stubs: { Button } })
  await flush()
  expect(telephony.defaultCallingMedium.value).toBe('Twilio')

  // the Default Medium select is the pane's first field
  const defaultMedium = formControls.find(
    (c) => c.props.modelValue === 'Twilio',
  )
  defaultMedium.type('Exotel')
  await flush()
  w.el.querySelector('button[data-label="Update"]').click()
  await flush()

  // what CallUI.makeCall reads
  expect(telephony.defaultCallingMedium.value).toBe('Exotel')
})
