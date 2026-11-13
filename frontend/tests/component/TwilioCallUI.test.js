import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'
import {
  Button,
  answers,
  calls,
  resetRecorders,
  setConfig,
  toasts,
} from './telephony/frappeUi.js'
import { FakeCall, connect, devices } from './telephony/twilioSdk.js'
import { useDoctypeModal } from '@/composables/doctypeModal'
import TwilioCallUI from '@/components/Telephony/TwilioCallUI.vue'
import { twilioHandover } from '@/components/Telephony/twilioHandover'

vi.mock('frappe-ui', () => import('./telephony/frappeUi.js'))
vi.mock('@twilio/voice-sdk', () => import('./telephony/twilioSdk.js'))

const flush = async (rounds = 6) => {
  for (let i = 0; i < rounds; i++) {
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

const button = (el, by, value) =>
  [...el.querySelectorAll('button.stub-Button')].find(
    (b) => b.dataset[by] === value,
  )

const visible = (node) => {
  for (let n = node; n && n.nodeType === 1; n = n.parentElement) {
    if (n.style?.display === 'none') return false
  }
  return true
}

const directory = {
  '+27115550001': { full_name: 'Alice First', mobile_no: '+27115550001' },
  '+27115550002': { full_name: 'Bongani Second', mobile_no: '+27115550002' },
}
let lookedUp

function mountCallUI() {
  return mount(TwilioCallUI, { stubs: { Button } })
}

// Twilio rings every registered Device of the rep's identity, each with its own
// leg of the call.
async function ring(params) {
  const legs = devices
    .filter((d) => d.state === 'registered')
    .map((device) => {
      const leg = new FakeCall(params)
      device.emit('incoming', leg)
      return leg
    })
  await flush()
  return legs
}

beforeEach(() => {
  resetRecorders()
  twilioHandover.current = null
  devices.length = 0
  connect.fail = null
  answers.call = (method) =>
    Promise.resolve(
      method.endsWith('generate_access_token') ? { token: 'token' } : {},
    )
  lookedUp = []
  setConfig('resourceFetcher', async ({ params }) => {
    lookedUp.push(params.phone_number)
    return directory[params.phone_number] || { mobile_no: params.phone_number }
  })
})

afterEach(() => {
  useDoctypeModal().show.value = false
})

describe('TwilioCallUI: a note taken during a call', () => {
  async function onAcceptedCall() {
    const w = mountCallUI()
    w.vm.setup()
    await flush()
    await ring({ From: '+27115550001', CallSid: 'CA-IN-1' })
    button(w.el, 'label', 'Accept').click()
    await flush()
    return w
  }

  it('opens a note form, not a new call log form', async () => {
    const w = await onAcceptedCall()
    button(w.el, 'tooltip', 'Add a Note').click()

    const modal = useDoctypeModal()
    expect(modal.show.value).toBe(true)
    expect(modal.doctype.value).toBe('FCRM Note')
  })

  it('links the saved note to the call, even once the call has ended', async () => {
    const w = await onAcceptedCall()
    button(w.el, 'tooltip', 'Add a Note').click()
    // the rep hangs up and then saves what they wrote
    button(w.el, 'tooltip', 'Hang Up').click()
    await flush()

    const modal = useDoctypeModal()
    modal.triggerCallback('afterInsert', {
      doctype: modal.doctype.value,
      name: 'NOTE-1',
      content: '<p>Wants a quote</p>',
    })
    await flush()

    const linked = calls.find(
      (c) => c.method === 'crm.integrations.api.add_note_to_call_log',
    )
    expect(linked.args.call_sid).toBe('CA-IN-1')
    expect(linked.args.note).toMatchObject({
      doctype: 'FCRM Note',
      name: 'NOTE-1',
    })
  })

  const saveNote = async (name) => {
    const modal = useDoctypeModal()
    modal.triggerCallback(modal.name.value ? 'afterUpdate' : 'afterInsert', {
      doctype: modal.doctype.value,
      name,
      content: '<p>Wants a quote</p>',
    })
    await flush()
  }

  it('a second note on the same call edits the note it saved', async () => {
    const w = await onAcceptedCall()
    button(w.el, 'tooltip', 'Add a Note').click()
    await saveNote('NOTE-1')

    button(w.el, 'tooltip', 'Add a Note').click()

    expect(useDoctypeModal().name.value).toBe('NOTE-1')
  })

  it('after the caller hangs up, the next call starts a note of its own', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await flush()
    const [first] = await ring({ From: '+27115550001', CallSid: 'CA-IN-1' })
    button(w.el, 'label', 'Accept').click()
    await flush()
    button(w.el, 'tooltip', 'Add a Note').click()
    await saveNote('NOTE-1')
    first.emit('disconnect')
    await flush()

    await ring({ From: '+27115550002', CallSid: 'CA-IN-2' })
    button(w.el, 'label', 'Accept').click()
    await flush()
    button(w.el, 'tooltip', 'Add a Note').click()

    expect(useDoctypeModal().name.value).toBe(null)
    calls.length = 0
    await saveNote('NOTE-2')
    expect(calls[0].args).toMatchObject({
      call_sid: 'CA-IN-2',
      note: { name: 'NOTE-2' },
    })
  })

  it('a note saved after the call ended is not reopened on the next call', async () => {
    const w = await onAcceptedCall()
    button(w.el, 'tooltip', 'Add a Note').click()
    button(w.el, 'tooltip', 'Hang Up').click()
    await flush()
    await saveNote('NOTE-1')

    await ring({ From: '+27115550002', CallSid: 'CA-IN-2' })
    button(w.el, 'label', 'Accept').click()
    await flush()
    button(w.el, 'tooltip', 'Add a Note').click()

    expect(useDoctypeModal().name.value).toBe(null)
  })

  it('a note saved once the next call is up goes to its own call, and stays there', async () => {
    const w = await onAcceptedCall()
    button(w.el, 'tooltip', 'Add a Note').click()
    button(w.el, 'tooltip', 'Hang Up').click()
    await flush()
    // the next call rings in while the rep is still writing up the last one
    await ring({ From: '+27115550002', CallSid: 'CA-IN-2' })
    button(w.el, 'label', 'Accept').click()
    await flush()
    await saveNote('NOTE-1')

    expect(calls.at(-1).args.call_sid).toBe('CA-IN-1')
    button(w.el, 'tooltip', 'Add a Note').click()
    expect(useDoctypeModal().name.value).toBe(null)
  })

  it('a call the rep places after one that rang in starts a note of its own', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await flush()
    const [first] = await ring({ From: '+27115550001', CallSid: 'CA-IN-1' })
    button(w.el, 'label', 'Accept').click()
    await flush()
    button(w.el, 'tooltip', 'Add a Note').click()
    await saveNote('NOTE-1')
    first.emit('disconnect')
    await flush()

    await w.vm.makeOutgoingCall('+27115550002')
    devices[0].lastCall.emit('messageReceived', {
      content: { CallStatus: 'in-progress' },
    })
    await flush()
    button(w.el, 'tooltip', 'Add a Note').click()

    expect(useDoctypeModal().name.value).toBe(null)
  })
})

describe('TwilioCallUI: a call that cannot be placed says why', () => {
  it('tells a rep with no Twilio number, instead of doing nothing', async () => {
    // crm.integrations.twilio.api.generate_access_token answers this, not a token
    answers.call = () =>
      Promise.resolve({
        ok: false,
        error: 'caller_phone_identity_missing',
        detail: 'Phone number is not mapped to the caller',
      })
    const w = mountCallUI()
    w.vm.setup()
    await flush()

    await w.vm.makeOutgoingCall('+27115550009')
    await flush()

    expect(devices).toHaveLength(0)
    expect(toasts).toEqual([
      ['error', 'Phone number is not mapped to the caller'],
    ])
  })

  it('tells the rep when the call does not connect', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await flush()
    connect.fail = new Error('Media acquisition failed')

    await w.vm.makeOutgoingCall('+27115550009')
    await flush()

    expect(toasts).toEqual([
      ['error', 'Could not connect the call: Media acquisition failed'],
    ])
  })
})

describe('TwilioCallUI: one Device for as long as it is mounted', () => {
  it('releases its Device when the layout unmounts it', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await flush()

    w.unmount()

    expect(devices.map((d) => d.state)).toEqual(['destroyed'])
  })

  it('does not hang up an answered call when the layout swaps mid-call', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await flush()
    const [leg] = await ring({ From: '+27115550001', CallSid: 'CA-LIVE' })
    button(w.el, 'label', 'Accept').click()
    await flush()

    w.unmount() // the window crossed the mobile breakpoint

    // kept, but no longer rung: the next header's Device takes new calls
    expect(devices[0].state).toBe('unregistered')
    leg.emit('disconnect') // the customer hangs up
    expect(devices[0].state).toBe('destroyed')
  })

  it('does not hang up a call the rep is placing when the layout swaps', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await flush()
    await w.vm.makeOutgoingCall('+27115550002')
    await flush()

    w.unmount()

    expect(devices[0].state).toBe('unregistered')
    devices[0].lastCall.emit('disconnect')
    expect(devices[0].state).toBe('destroyed')
  })

  it('gives the next popup the surviving call, with a Hang Up that ends it', async () => {
    const first = mountCallUI()
    first.vm.setup()
    await flush()
    const [leg] = await ring({ From: '+27115550001', CallSid: 'CA-LIVE' })
    button(first.el, 'label', 'Accept').click()
    await flush()
    first.unmount() // the layout swapped

    const second = mountCallUI()
    second.vm.setup()
    await flush()
    // the caller, and the controls of a call that is up
    expect(second.el.textContent).toContain('Alice First')
    const hangUp = button(second.el, 'tooltip', 'Hang Up')
    expect(hangUp && visible(hangUp)).toBe(true)
    expect(button(second.el, 'label', 'Accept')).toBeUndefined()

    let ended = 0
    leg.on('disconnect', () => ended++)
    hangUp.click()
    await flush()
    expect(ended).toBe(1)
    const after = button(second.el, 'tooltip', 'Hang Up')
    expect(!after || !visible(after)).toBe(true)
    // the Device that carried it goes with it; the new one is untouched
    expect(devices.map((d) => d.state)).toEqual(['destroyed', 'registered'])
    expect(twilioHandover.current).toBe(null)
  })

  it('can mute the surviving call from the next popup', async () => {
    const first = mountCallUI()
    first.vm.setup()
    await flush()
    const [leg] = await ring({ From: '+27115550001', CallSid: 'CA-LIVE' })
    button(first.el, 'label', 'Accept').click()
    await flush()
    first.unmount()

    const second = mountCallUI()
    await flush()
    second.vm.$.setupState.toggleMute()
    expect(leg.isMuted()).toBe(true)
  })

  it('carries a call the rep is still placing over, and follows it to answered', async () => {
    const first = mountCallUI()
    first.vm.setup()
    await flush()
    await first.vm.makeOutgoingCall('+27115550002')
    await flush()
    const leg = devices[0].lastCall
    first.unmount()

    const second = mountCallUI()
    await flush()
    const cancel = button(second.el, 'label', 'Cancel')
    expect(cancel && visible(cancel)).toBe(true)
    leg.emit('messageReceived', { content: { CallStatus: 'in-progress' } })
    await flush()
    const hangUp = button(second.el, 'tooltip', 'Hang Up')
    expect(hangUp && visible(hangUp)).toBe(true)
  })

  it('survives a second swap: the call is handed on again, its Device kept', async () => {
    const first = mountCallUI()
    first.vm.setup()
    await flush()
    const [leg] = await ring({ From: '+27115550001', CallSid: 'CA-LIVE' })
    button(first.el, 'label', 'Accept').click()
    await flush()
    first.unmount()
    const second = mountCallUI()
    second.vm.setup()
    await flush()
    second.unmount() // swapped back

    // the idle Device of the second popup is released; the call's is not
    expect(devices.map((d) => d.state)).toEqual(['unregistered', 'destroyed'])
    const third = mountCallUI()
    await flush()
    const hangUp = button(third.el, 'tooltip', 'Hang Up')
    expect(hangUp && visible(hangUp)).toBe(true)
    leg.emit('disconnect')
    expect(devices[0].state).toBe('destroyed')
  })

  it('keeps the call up through an error that did not end it', async () => {
    const first = mountCallUI()
    first.vm.setup()
    await flush()
    const [leg] = await ring({ From: '+27115550001', CallSid: 'CA-LIVE' })
    button(first.el, 'label', 'Accept').click()
    await flush()
    first.unmount()
    const second = mountCallUI()
    await flush()

    // the SDK raises `error` for a message or a DTMF tone that failed; the
    // call is still open, and destroying its Device would hang up on the rep
    leg.emit('error', new Error('31209 message failed to send'))
    await flush()
    expect(devices[0].state).toBe('unregistered')
    expect(twilioHandover.current?.call).toBe(leg)
    const hangUp = button(second.el, 'tooltip', 'Hang Up')
    expect(hangUp && visible(hangUp)).toBe(true)
  })

  it('destroys the kept Device once when the call ends, error or not', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await flush()
    const [leg] = await ring({ From: '+27115550001', CallSid: 'CA-LIVE' })
    button(w.el, 'label', 'Accept').click()
    await flush()
    w.unmount()

    let destroyed = 0
    const destroy = devices[0].destroy.bind(devices[0])
    devices[0].destroy = () => (destroyed++, destroy())
    // an error that closed the call, then the disconnect that follows it
    leg.state = 'closed'
    leg.emit('error', new Error('31005 connection error'))
    expect(devices[0].state).toBe('destroyed')
    leg.emit('disconnect')
    expect(destroyed).toBe(1)
    expect(twilioHandover.current).toBe(null)
  })

  it('does not let a second caller take the popup from a handed-over call', async () => {
    const first = mountCallUI()
    first.vm.setup()
    await flush()
    const [leg] = await ring({ From: '+27115550001', CallSid: 'CA-LIVE' })
    button(first.el, 'label', 'Accept').click()
    await flush()
    first.unmount()
    const second = mountCallUI()
    second.vm.setup()
    await flush()

    // only the new popup's Device is registered, and it has no call of its
    // own, so the SDK surfaces the second caller to it
    const [other] = await ring({ From: '+27115550002', CallSid: 'CA-2ND' })
    expect(other.ignored).toBe(true)
    expect(second.el.textContent).toContain('Alice First')
    expect(button(second.el, 'label', 'Accept')).toBeUndefined()

    // the controls still act on the call the rep is on
    second.vm.$.setupState.toggleMute()
    expect(leg.isMuted()).toBe(true)
    expect(other.isMuted()).toBe(false)
    button(second.el, 'tooltip', 'Hang Up').click()
    await flush()
    expect(leg.status()).toBe('closed')
    expect(other.status()).toBe('open')

    // and once it is over, the next caller rings as usual
    const [next] = await ring({ From: '+27115550002', CallSid: 'CA-3RD' })
    expect(next.ignored).toBe(false)
    const accept = button(second.el, 'label', 'Accept')
    expect(accept && visible(accept)).toBe(true)
  })

  it('refreshes the token of a Device kept for a live call without throwing', async () => {
    const rejections = []
    const onRejection = (reason) => rejections.push(reason)
    process.on('unhandledRejection', onRejection)
    try {
      const w = mountCallUI()
      w.vm.setup()
      await flush()
      await ring({ From: '+27115550001', CallSid: 'CA-LIVE' })
      button(w.el, 'label', 'Accept').click()
      await flush()
      w.unmount()

      answers.call = () => Promise.resolve({ token: 'token-2' })
      devices[0].emit('tokenWillExpire')
      await flush()
      expect(devices[0].token).toBe('token-2')

      // and a refresh that fails is reported, not thrown
      const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
      answers.call = () => Promise.reject(new Error('503'))
      devices[0].emit('tokenWillExpire')
      await flush()
      expect(logged).toHaveBeenCalled()
      logged.mockRestore()
      expect(rejections).toEqual([])
    } finally {
      process.off('unhandledRejection', onRejection)
    }
  })

  it('still releases a Device whose call is only ringing in', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await flush()
    await ring({ From: '+27115550001', CallSid: 'CA-RING' })

    w.unmount()

    expect(devices[0].state).toBe('destroyed')
  })

  it('a second setup() keeps one Device, so an accepted call stays up', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await flush()
    // CallUI calls setup() again whenever telephony is switched back on
    w.vm.setup()
    await flush()

    expect(devices.filter((d) => d.state === 'registered')).toHaveLength(1)
    const [, ...otherLegs] = await ring({
      From: '+27115550001',
      CallSid: 'CA-1',
    })
    button(w.el, 'label', 'Accept').click()
    await flush()
    // answering one leg cancels the rest
    for (const leg of otherLegs) leg.emit('cancel')
    await flush()
    const hangUp = button(w.el, 'tooltip', 'Hang Up')
    expect(hangUp && visible(hangUp)).toBe(true)
  })
})

describe('TwilioCallUI: the caller lookup', () => {
  it('after a remount, shows the caller who is ringing now', async () => {
    const first = mountCallUI()
    first.vm.setup()
    await flush()
    await ring({ From: '+27115550001', CallSid: 'CA-1' })
    expect(first.el.textContent).toContain('Alice First')
    first.unmount()

    // the window crossed the mobile breakpoint: the other header's instance
    const second = mountCallUI()
    second.vm.setup()
    await flush()
    await ring({ From: '+27115550002', CallSid: 'CA-2' })

    expect(lookedUp.at(-1)).toBe('+27115550002')
    expect(second.el.textContent).toContain('Bongani Second')
  })
})
