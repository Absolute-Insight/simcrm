import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import { setConfig } from 'frappe-ui'
import CallArea from '@/components/Activities/CallArea.vue'

const S = vi.hoisted(() => ({ requests: [], modal: null }))

vi.mock('@/components/Modals/CallLogDetailModal.vue', () => ({
  default: {
    props: { modelValue: Boolean, callLog: { type: Object, default: null } },
    setup(props) {
      S.modal = props
      return () => null
    },
  },
}))
vi.mock('@/components/Activities/AudioPlayer.vue', () => ({
  default: {
    props: { src: { type: String, default: '' } },
    setup: (props) => () => h('audio', { src: props.src }),
  },
}))
vi.mock('@/components/MultipleAvatar.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/utils', () => ({ formatDate: (d) => String(d) }))
vi.mock('@/utils/callLog.js', () => ({
  getCallStatusLabel: (s) => s,
  statusColorMap: {},
}))
vi.mock('@/components/Activities/TimelineTimestamp.vue', () => ({
  default: { render: () => null },
}))

// The row get_activities sends: everything the card renders.
function row(name) {
  return {
    name,
    type: 'Outgoing',
    activity_type: 'outgoing_call',
    status: 'Completed',
    creation: '2026-10-29 10:00:00',
    recording_url: 'https://pbx.example/rec/' + name,
    _caller: { label: 'Rep', image: '' },
    _receiver: { label: 'Customer', image: '' },
    _duration: '1m',
  }
}

const getCallLog = () =>
  S.requests.filter((url) => url.endsWith('.get_call_log')).length

async function settle() {
  for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r))
}

describe('CallArea', () => {
  beforeEach(() => {
    S.requests.length = 0
    setConfig('resourceFetcher', ({ url, params }) => {
      S.requests.push(url)
      return Promise.resolve({
        name: params.name,
        recording_url_path: '/recordings/' + params.name,
      })
    })
  })

  it('renders a call from its timeline row without fetching the call log', async () => {
    for (const name of ['CALL-1', 'CALL-2', 'CALL-3']) {
      mount(CallArea, { props: { activity: row(name) } })
    }
    await settle()
    expect(getCallLog()).toBe(0)
  })

  it('fetches the call log when its details are opened', async () => {
    const w = mount(CallArea, { props: { activity: row('CALL-4') } })
    w.el.querySelector('.cursor-pointer.flex-col').click()
    await settle()

    expect(S.modal.modelValue).toBe(true)
    expect(getCallLog()).toBe(1)
    expect(S.modal.callLog.data.name).toBe('CALL-4')
  })

  it('fetches the recording when Listen is pressed', async () => {
    const w = mount(CallArea, { props: { activity: row('CALL-5') } })
    const listen = [...w.el.querySelectorAll('*')].find(
      (n) => n.textContent.trim() === 'Listen' && n.children.length <= 2,
    )
    listen.click()
    await settle()

    expect(getCallLog()).toBe(1)
    expect(w.el.querySelector('audio').getAttribute('src')).toBe(
      '/recordings/CALL-5',
    )
  })
})
