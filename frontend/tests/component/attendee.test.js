import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, reactive } from 'vue'
import { setConfig } from 'frappe-ui'
import { mount } from './mount.js'

// The Calendar/EventModal attendee picker: the real component, the real reka
// combobox and frappe-ui's real createResource; only the server is fake.
// Audit FE-34, FE-90, FE-91.

vi.mock('@/components/UserAvatar.vue', () => ({
  default: { render: () => null },
}))

const { default: Attendee } = await import('@/components/Calendar/Attendee.vue')

// contacts per search text, as crm.api.contact.search_emails answers
const DIRECTORY = {
  '': [['Default Person', 'default@client.test', 'C-DEF']],
  acme: [['Acme Buyer', 'buyer@acme.test', 'C-ACME']],
  'colleague@mbp.test': [['Colleague Two', 'colleague2@mbp.test', 'C-TWO']],
}
const searches = []
setConfig('resourceFetcher', async ({ url, params }) => {
  if (url !== 'crm.api.contact.search_emails') throw new Error(url)
  searches.push(params.txt)
  return DIRECTORY[params.txt] || []
})

const ErrorMessage = defineComponent({
  props: ['message'],
  setup: (p) => () => h('p', { class: 'error' }, p.message),
})
const Button = defineComponent({
  props: ['label'],
  setup:
    (p, { slots }) =>
    () =>
      h('div', [p.label, slots.suffix?.()]),
})

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const flush = async () => {
  for (let i = 0; i < 5; i++) {
    await nextTick()
    await sleep(0)
  }
}

/** The picker as the event panel holds it: its model fed back. */
function picker(initial = []) {
  const model = reactive({ value: initial })
  const emitted = []
  const Host = defineComponent({
    setup: () => () =>
      h(Attendee, {
        modelValue: model.value,
        'onUpdate:modelValue': (v) => {
          emitted.push(v)
          model.value = v
        },
        validate: (e) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e),
        errorMessage: (v) => `${v} is an invalid email address`,
      }),
  })
  const w = mount(Host, { stubs: { ErrorMessage, Button } })
  const input = () => w.el.querySelector('input')
  return {
    ...w,
    emitted,
    async type(text) {
      input().value = text
      input().dispatchEvent(new Event('input', { bubbles: true }))
      await flush()
    },
    async enter() {
      input().dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          cancelable: true,
        }),
      )
      await flush()
    },
    added: () => (emitted.at(-1) || []).map((a) => a.email),
  }
}

beforeEach(() => {
  searches.length = 0
})
afterEach(async () => {
  await sleep(350) // let a pending debounced search of an unmounted picker go
})

describe('Attendee: Enter adds what was typed (FE-34)', () => {
  it('right after pasting, before the search has answered', async () => {
    const p = picker()
    await sleep(350) // the suggestions for '' have arrived
    await p.type('colleague@mbp.test')
    await p.enter()
    expect(p.added()).toEqual(['colleague@mbp.test'])
    expect(p.emitted.at(-1)[0].reference_docname).toBe('new')
  })

  it('after the search answered with a different contact', async () => {
    const p = picker()
    await sleep(350)
    await p.type('colleague@mbp.test')
    await sleep(350)
    expect(searches).toContain('colleague@mbp.test')
    await p.enter()
    expect(p.added()).toEqual(['colleague@mbp.test'])
  })
})

describe('Attendee: an invalid address (FE-90)', () => {
  it('is refused with a message, also when it is the first one', async () => {
    const p = picker()
    await p.type('not-an-email')
    await p.enter()
    expect(p.added()).toEqual([])
    expect(p.el.textContent).toContain(
      'not-an-email is an invalid email address',
    )
  })
})

describe('Attendee: a newly opened picker (FE-91)', () => {
  it('offers its own suggestions, not the previous picker search', async () => {
    const first = picker()
    await sleep(350)
    await first.type('acme')
    await sleep(350)
    first.unmount() // the panel is closed

    searches.length = 0
    const second = picker()
    await sleep(350)
    expect(searches).toEqual([''])
    second.el.querySelector('input').parentElement.click() // open the list
    await flush()
    expect(document.body.textContent).toContain('default@client.test')
    expect(document.body.textContent).not.toContain('buyer@acme.test')
  })
})

describe('Attendee: rows without an email', () => {
  it("shows a visit's organisation and removes only the row clicked", async () => {
    const org = {
      email: '',
      reference_doctype: 'CRM Organization',
      reference_docname: 'Impala Springs',
    }
    const p = picker([org, { email: 'buyer@client.test' }])
    await flush()
    expect(p.el.textContent).toContain('Impala Springs')
    p.el.querySelectorAll('.lucide-x')[1].click() // the buyer's chip
    await flush()
    expect(p.emitted.at(-1)).toEqual([org])
  })
})
