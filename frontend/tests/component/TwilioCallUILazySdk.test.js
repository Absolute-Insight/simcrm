import { expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'
import { Button, answers } from './telephony/frappeUi.js'
import TwilioCallUI from '@/components/Telephony/TwilioCallUI.vue'

// Its own file, so the SDK module is fresh: whether it has been evaluated yet
// is the whole question.
const sdk = vi.hoisted(() => ({ evaluated: 0 }))

vi.mock('frappe-ui', () => import('./telephony/frappeUi.js'))
vi.mock('@twilio/voice-sdk', () => {
  sdk.evaluated++
  return {
    Device: class {
      on() {}
      register() {}
      destroy() {}
    },
  }
})

it('loads the Twilio Voice SDK only when Twilio is set up', async () => {
  // CallUI sits in both app headers, so this component is in the chunk every
  // page loads; the SDK is ~50 KB gzipped that a site without Twilio never uses.
  const w = mount(TwilioCallUI, { stubs: { Button } })
  await nextTick()
  expect(sdk.evaluated).toBe(0)

  answers.call = () => Promise.resolve({ token: 'token' })
  await w.vm.setup()
  expect(sdk.evaluated).toBe(1)
})
