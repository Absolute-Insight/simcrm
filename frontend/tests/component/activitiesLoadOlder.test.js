import { ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// The timeline used to be desk's first screen of history -- ten saves and 21
// emails -- with nothing to say the rest was missing. get_activities now pages
// and says `has_more`; the timeline has to offer the older history.

const state = vi.hoisted(() => ({ resources: [], newestFirst: null }))

const passthrough = vi.hoisted(() => async () => {
  const { defineComponent, h } = await import('vue')
  return {
    // props the parent passes fall through as attributes otherwise, and an
    // object can't be one
    default: defineComponent({
      inheritAttrs: false,
      setup:
        (_, { slots }) =>
        () =>
          h('div', slots.default?.()),
    }),
  }
})

vi.mock('frappe-ui', async () => {
  const { defineComponent, h, reactive } = await import('vue')
  return {
    Button: defineComponent({
      props: { label: { type: String, default: '' } },
      emits: ['click'],
      setup:
        (props, { emit }) =>
        () =>
          h('button', { onClick: () => emit('click') }, props.label),
    }),
    toast: { success: vi.fn(), error: vi.fn() },
    createResource(options) {
      const resource = reactive({
        options,
        params: options.params,
        data: null,
        loading: false,
        update: vi.fn(({ params }) => {
          resource.params = params
        }),
        reload: vi.fn(),
        fetch: vi.fn(),
      })
      state.resources.push(resource)
      return resource
    },
  }
})

vi.mock('@/components/Activities/ActivityHeader.vue', passthrough)
vi.mock('@/components/Activities/EmailArea.vue', passthrough)
vi.mock('@/components/Activities/CommentArea.vue', passthrough)
vi.mock('@/components/Activities/CallArea.vue', passthrough)
vi.mock('@/components/Activities/NoteArea.vue', passthrough)
vi.mock('@/components/Activities/TaskArea.vue', passthrough)
vi.mock('@/components/Activities/AttachmentArea.vue', passthrough)
vi.mock('@/components/Activities/DataFields.vue', passthrough)
vi.mock('@/components/Activities/EventArea.vue', passthrough)
vi.mock('@/components/Activities/WhatsAppArea.vue', passthrough)
vi.mock('@/components/Activities/WhatsAppBox.vue', passthrough)
vi.mock('@/components/Activities/AllModals.vue', passthrough)
vi.mock('@/components/Activities/TimelineTimestamp.vue', passthrough)
vi.mock('@/components/UserAvatar.vue', passthrough)
vi.mock('@/components/ListViews/EmptyState.vue', passthrough)
vi.mock('@/components/CommunicationArea.vue', passthrough)
vi.mock('@/components/Modals/WhatsappTemplateSelectorModal.vue', passthrough)
vi.mock('@/components/FilesUploader/FilesUploader.vue', passthrough)
vi.mock('@/stores/global', () => ({
  globalStore: () => ({
    $socket: { on: vi.fn(), off: vi.fn(), emit: vi.fn() },
  }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: () => ({ full_name: 'Someone' }) }),
}))
vi.mock('@/composables/useTimelinePreferences', () => ({
  useTimelinePreferences: () => ({ isNewestFirst: state.newestFirst }),
}))
vi.mock('@/composables/whatsapp', async () => {
  const { ref } = await import('vue')
  return { whatsappEnabled: ref(false) }
})
vi.mock('@/data/document', () => ({
  useDocument: () => ({ document: { doc: {}, reload: vi.fn() } }),
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ hash: '' }) }))

const { default: Activities } = await import(
  '@/components/Activities/Activities.vue'
)

const email = {
  activity_type: 'communication',
  creation: '2026-10-01 10:00:00',
  data: { sender: 'someone@example.com', subject: 'Hello' },
}

function mountTimeline({ hasMore, newestFirst = false }) {
  state.resources.length = 0
  state.newestFirst = ref(newestFirst)
  const wrapper = mount(Activities, {
    props: {
      doctype: 'CRM Deal',
      docname: 'CRM-DEAL-1',
      tabs: [{ name: 'Activity' }],
    },
  })
  const timeline = state.resources.find(
    (r) => r.options.url === 'crm.api.activities.get_activities',
  )
  // what get_activities answers: [activities, calls, notes, tasks, attachments, has_more]
  timeline.data = timeline.options.transform([
    [{ ...email }],
    [],
    [],
    [],
    [],
    hasMore,
  ])
  return { wrapper, timeline }
}

function loadOlderButton(wrapper) {
  return [...wrapper.el.querySelectorAll('button')].find(
    (b) => b.textContent.trim() === 'Load older activity',
  )
}

afterEach(() => vi.clearAllMocks())

describe('Activities timeline paging', () => {
  it('offers the older history when the server says there is more', async () => {
    const { wrapper, timeline } = mountTimeline({ hasMore: true })
    await wrapper.nextTick()

    const button = loadOlderButton(wrapper)
    expect(button, 'a "Load older activity" button').toBeTruthy()

    timeline.reload.mockClear() // the load every timeline tab starts with
    button.click()
    expect(timeline.update).toHaveBeenCalledWith({
      params: { name: 'CRM-DEAL-1', page_length: 200 },
    })
    expect(timeline.reload).toHaveBeenCalledOnce()
  })

  it('offers nothing when the whole history is already there', async () => {
    const { wrapper } = mountTimeline({ hasMore: false })
    await wrapper.nextTick()

    expect(loadOlderButton(wrapper)).toBeUndefined()
  })

  it('puts the button at the older end of a newest-first timeline', async () => {
    const { wrapper } = mountTimeline({ hasMore: true, newestFirst: true })
    await wrapper.nextTick()

    const button = loadOlderButton(wrapper)
    const rows = wrapper.el.querySelectorAll('.activity')
    expect(
      rows[rows.length - 1].compareDocumentPosition(button) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })
})
