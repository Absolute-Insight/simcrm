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
