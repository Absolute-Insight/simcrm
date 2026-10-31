import { expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'
import { Dialog, setConfig } from './telephony/frappeUi.js'

// The two providers are replaced by spies: what is under test is which one
// CallUI hands the number to.
const providers = vi.hoisted(() => {
  const state = { makeCall: null, dialled: [], setUp: [] }
  const spy = (name) => async () => {
    const { defineComponent, h } = await import('vue')
    return {
      default: defineComponent({
        name,
        setup(_, { expose }) {
          expose({
            setup: () => state.setUp.push(name),
            makeOutgoingCall: (number) => state.dialled.push([name, number]),
          })
          return () => h('div')
        },
      }),
    }
  }
  return { state, spy }
})

vi.mock('frappe-ui', () => import('./telephony/frappeUi.js'))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({
    setMakeCall: (fn) => (providers.state.makeCall = fn),
  }),
}))
vi.mock('@/components/Telephony/TwilioCallUI.vue', providers.spy('Twilio'))
vi.mock('@/components/Telephony/ExotelCallUI.vue', providers.spy('Exotel'))

const flush = async (rounds = 6) => {
  for (let i = 0; i < rounds; i++) {
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

// What crm.integrations.api.is_call_integration_enabled answers at boot: an
// admin has since switched Twilio off and Exotel on, and this rep's saved
// default is still Twilio. Set before the telephony composable loads, since it
// asks as soon as it is imported.
setConfig('resourceFetcher', async ({ url }) =>
  url.endsWith('is_call_integration_enabled')
    ? {
        integrations: { twilio: false, exotel: true },
        default_calling_medium: 'Twilio',
      }
    : {},
)
const { default: CallUI } = await import('@/components/Telephony/CallUI.vue')

it('calls through the enabled provider, not a saved default that was switched off', async () => {
  mount(CallUI, { stubs: { Dialog } })
  await flush()
  expect(providers.state.setUp).toEqual(['Exotel'])

  providers.state.makeCall('+27115550001')
  await flush()

  expect(providers.state.dialled).toEqual([['Exotel', '+27115550001']])
})
