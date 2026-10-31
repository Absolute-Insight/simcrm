import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, reactive } from 'vue'
import { mount } from './mount.js'
import { Button, setConfig } from './telephony/frappeUi.js'

const documents = vi.hoisted(() => ({}))

vi.mock('frappe-ui', () => import('./telephony/frappeUi.js'))
vi.mock('@/data/document', () => ({
  useDocument: (doctype) => ({ document: documents[doctype] }),
}))
vi.mock('@/components/ui/CheckSwitch.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/ui/ErrorState.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/ui/ToneBadge.vue', () => ({
  default: { render: () => null },
}))

const flush = async (rounds = 4) => {
  for (let i = 0; i < rounds; i++) {
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

const Layout = defineComponent({
  setup:
    (_, { slots }) =>
    () =>
      h('div', [
        slots.title?.(),
        slots['header-actions']?.(),
        slots.content?.(),
      ]),
})
const Blank = { render: () => null }
const stubs = {
  SettingsLayoutBase: Layout,
  Button,
  FormControl: Blank,
  Password: Blank,
  LoadingIndicator: Blank,
  PhoneIcon: Blank,
}

/* A settings document whose save the server either stores or refuses, the way
   frappe-ui's save.submit behaves: onSuccess with the stored document, or a
   rejection (the document's own save handler toasts the message). */
function settingsDocument(doc, { refuse = false } = {}) {
  const document = reactive({
    doc: { ...doc },
    originalDoc: { ...doc },
    get: { loading: false, error: null },
    reload: vi.fn(),
    fetchTwilioApps: { loading: false, fetch: vi.fn() },
    save: {
      loading: false,
      submit: vi.fn(async (_params, options) => {
        if (refuse) {
          throw Object.assign(new Error('Invalid Account SID or Auth Token.'), {
            messages: ['Invalid Account SID or Auth Token.'],
          })
        }
        const stored = { ...document.doc }
        options?.onSuccess?.(stored)
        return stored
      }),
    },
  })
  return document
}

setConfig('resourceFetcher', async () => ({}))
const telephony = await import('@/composables/telephony')
const settingsPanes = {
  twilio: (await import('@/components/Settings/Telephony/TwilioSettings.vue'))
    .default,
  exotel: (await import('@/components/Settings/Telephony/ExotelSettings.vue'))
    .default,
}

beforeEach(async () => {
  await flush() // the boot fetch of is_call_integration_enabled settles first
  telephony.setEnabled('twilio', false)
  telephony.setEnabled('exotel', false)
})

async function press(component, label) {
  const w = mount(component, { stubs })
  await flush()
  return {
    w,
    async click(name = label) {
      w.el.querySelector(`button[data-label="${name}"]`).click()
      await flush()
    },
  }
}

const providers = [
  {
    name: 'twilio',
    doctype: 'CRM Twilio Settings',
    credentials: { account_sid: 'ACbad', auth_token: '***' },
  },
  {
    name: 'exotel',
    doctype: 'CRM Exotel Settings',
    credentials: { account_sid: 'bad', api_key: 'k', api_token: '***' },
  },
]

describe.each(providers)(
  '$doctype: calling follows what was stored, not the toggle',
  ({ name, doctype, credentials }) => {
    async function enableAndUpdate({ refuse }) {
      documents[doctype] = settingsDocument({ enabled: 0 }, { refuse })
      const pane = await press(settingsPanes[name])
      await pane.click('Enable')
      Object.assign(documents[doctype].doc, credentials)
      await flush()
      await pane.click('Update')
    }

    it('a refused save does not turn calling on', async () => {
      await enableAndUpdate({ refuse: true })

      expect(documents[doctype].save.submit).toHaveBeenCalledOnce()
      expect(telephony.useTelephony().isEnabled(name)).toBe(false)
      expect(telephony.callEnabled.value).toBe(false)
    })

    it('a stored save does', async () => {
      await enableAndUpdate({ refuse: false })

      expect(telephony.useTelephony().isEnabled(name)).toBe(true)
      expect(telephony.callEnabled.value).toBe(true)
    })

    it('a refused disable does not report calling as off', async () => {
      telephony.setEnabled(name, true)
      documents[doctype] = settingsDocument(
        { enabled: 1, ...credentials },
        { refuse: true },
      )
      const pane = await press(settingsPanes[name])

      await pane.click('Disable')

      expect(telephony.useTelephony().isEnabled(name)).toBe(true)
    })
  },
)
