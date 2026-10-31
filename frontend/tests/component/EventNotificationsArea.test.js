import { describe, expect, it, vi } from 'vitest'
import { h, nextTick, ref } from 'vue'
import { dayjs } from 'frappe-ui'
import isBetween from 'dayjs/plugin/isBetween'
import { mount } from './mount.js'
import EventNotificationsArea from '@/components/EventNotificationsArea.vue'

// the real @/data/notifications extends dayjs with this as it loads
dayjs.extend(isBetween)

const events = ref([])

vi.mock('@/data/notifications', () => ({
  useEventNotifications: () => ({ events, eventsResource: {} }),
}))
vi.mock('@/stores/notifications', () => ({
  notificationsStore: () => ({ toggle: () => {} }),
}))
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useRouter: () => ({ push: () => {} }),
}))

const at = (minutes) =>
  dayjs().add(minutes, 'minute').format('YYYY-MM-DD HH:mm:ss')

const event = (name, subject, startsIn, endsIn) => ({
  name,
  subject,
  starts_on: at(startsIn),
  ends_on: at(endsIn),
  all_day: 0,
  participants: [],
})

// Both registered globally in main.js.
const Badge = { props: ['label'], setup: (p) => () => h('span', p.label) }
const CollapsibleSection = {
  setup:
    (_, { slots }) =>
    () =>
      h('section', [
        slots.header?.({ opened: true, toggle: () => {} }),
        slots.default?.(),
      ]),
}

const render = () =>
  mount(EventNotificationsArea, { stubs: { Badge, CollapsibleSection } })

describe('Notifications -> Events', () => {
  it('does not list an event that has already ended as upcoming', async () => {
    events.value = [
      event('EV-1', 'Site visit (already over)', -90, -30),
      event('EV-2', 'Pump station walk-through', 120, 180),
    ]
    const w = render()
    await nextTick()

    const text = w.el.textContent.replace(/\s+/g, ' ')
    expect(text).toContain('Upcoming events')
    expect(text).toContain('Pump station walk-through')
    expect(text).not.toContain('Site visit (already over)')
  })

  it('says there is nothing upcoming when every event has ended', async () => {
    events.value = [event('EV-1', 'Site visit (already over)', -90, -30)]
    const w = render()
    await nextTick()

    expect(w.el.textContent).toContain('No Upcoming Events')
  })
})
