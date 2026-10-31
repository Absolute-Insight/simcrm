import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { mount } from './mount.js'

// The real EmailMultiSelect, frappe-ui Button and createResource, and reka-ui
// Combobox; only the avatar and the users store are stubbed.
vi.mock('@/components/UserAvatar.vue', () => ({
  default: defineComponent({ setup: () => () => h('span') }),
}))
vi.mock('@/stores/users', async () => {
  const { ref } = await import('vue')
  return { usersStore: () => ({ allUsers: ref([]) }) }
})

const { Button, ErrorMessage, setConfig } = await import('frappe-ui')
const searches = []
setConfig('resourceFetcher', async ({ params }) => {
  searches.push(params.txt)
  return params.txt
    ? [[`${params.txt} Smith`, `${params.txt}@client.co.za`, 'C-9']]
    : [
        ['Ann Buyer', 'ann@client.co.za', 'C-1'],
        ['Bob Eng', 'bob@client.co.za', 'C-2'],
      ]
})
const EmailMultiSelect = (
  await import('@/components/Controls/EmailMultiSelect.vue')
).default

const stubs = { Button, ErrorMessage } // registered globally in main.js

// Through a parent holding the v-model, as EmailEditor does.
function recipients(props, initial = []) {
  const values = ref(initial)
  const Parent = defineComponent({
    setup: () => () =>
      h(EmailMultiSelect, {
        ...props,
        modelValue: values.value,
        'onUpdate:modelValue': (v) => (values.value = v),
      }),
  })
  return { ...mount(Parent, { stubs }), values }
}

const backspace = () =>
  document.activeElement.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Backspace', bubbles: true }),
  )

describe('EmailMultiSelect', () => {
  it('Backspace in the empty input focuses, then removes, the last chip', async () => {
    const w = recipients({}, ['a@example.com', 'b@example.com'])
    await w.nextTick()
    w.el.querySelector('input').focus()

    backspace()
    await w.nextTick()
    expect(document.activeElement.textContent).toContain('b@example.com')

    backspace()
    await w.nextTick()
    await w.nextTick()
    expect(w.values.value).toEqual(['a@example.com'])
    expect(document.activeElement.textContent).toContain('a@example.com')
    w.unmount()
  })

  it("a search typed in one recipient field leaves another's options alone", async () => {
    const to = recipients({ fetchContacts: true })
    const cc = recipients({ fetchContacts: true })
    await vi.waitFor(() => expect(searches).toContain(''))

    const ccInput = cc.el.querySelector('input')
    ccInput.value = 'john'
    ccInput.dispatchEvent(new Event('input', { bubbles: true }))
    await vi.waitFor(() => expect(searches).toContain('john'), {
      timeout: 1000,
    })
    ccInput.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
    )

    // To's own query is still '', so it should still offer the full list.
    const toInput = to.el.querySelector('input')
    toInput.dispatchEvent(new FocusEvent('focus'))
    const offered = () =>
      [
        ...(document
          .getElementById(toInput.getAttribute('aria-controls'))
          ?.querySelectorAll('[role="option"]') || []),
      ].map((o) => o.textContent)
    await vi.waitFor(() => expect(offered().length).toBeGreaterThan(0))
    expect(offered().join(' ')).toContain('ann@client.co.za')
    expect(offered().join(' ')).not.toContain('john@client.co.za')
    to.unmount()
    cc.unmount()
  })
})
