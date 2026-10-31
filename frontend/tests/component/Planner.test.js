import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { mount } from './mount.js'
import { addDays, mondayOf, todayInTimeZone } from '@/utils/planner'
import Planner from '@/pages/Planner.vue'

/* Planner on frappe-ui's real createResource, with a fetcher that parks every
   request until the test answers it: the order responses come back in is what
   these tests are about, and a real network does not promise one. `call`
   (the one-shot endpoints) is answered the same way. */
const { net, ui, parked, slots } = vi.hoisted(() => ({
  net: { requests: [], calls: [] },
  ui: { selects: {}, dialog: null },
  parked: (list, entry) =>
    new Promise((resolve, reject) =>
      list.push({ ...entry, resolve, reject, done: false }),
    ),
  // a component that renders every slot it is given, header slots included
  slots: (name) =>
    import('vue').then(({ h }) => ({
      default: {
        name,
        render() {
          return h(
            'div',
            Object.values(this.$slots).map((slot) => slot?.()),
          )
        },
      },
    })),
}))

vi.mock('frappe-ui', async () => {
  const { createResource } = await import(
    '../../node_modules/frappe-ui/src/resources/resources.js'
  )
  const { getConfig, setConfig } = await import(
    '../../node_modules/frappe-ui/src/utils/config.ts'
  )
  const { dayjs } = await import(
    '../../node_modules/frappe-ui/src/utils/dayjs.ts'
  )
  const { h } = await import('vue')
  setConfig('resourceFetcher', (options) =>
    parked(net.requests, { url: options.url, params: options.params || {} }),
  )
  const passThrough = (name) => ({
    name,
    render() {
      return h('div', this.$slots.default?.())
    },
  })
  return {
    createResource,
    getConfig,
    setConfig,
    dayjs,
    call: (method, args) => parked(net.calls, { method, args }),
    toast: Object.assign(() => {}, { error: () => {}, success: () => {} }),
    usePageMeta: () => {},
    Tooltip: passThrough('Tooltip'),
    Select: {
      name: 'Select',
      inheritAttrs: false,
      render() {
        ui.selects[this.$attrs['aria-label']] = this.$attrs
        return h('div')
      },
    },
    Dropdown: {
      name: 'Dropdown',
      props: ['options'],
      render() {
        return h('div', [
          ...(this.options || []).map((o) =>
            h('button', { 'data-label': o.label, onClick: o.onClick }, o.label),
          ),
          this.$slots.default?.(),
        ])
      },
    },
  }
})

vi.mock('@/components/LayoutHeader.vue', () => slots('LayoutHeader'))
vi.mock('@/components/ViewBreadcrumbs.vue', () => slots('ViewBreadcrumbs'))
vi.mock('@/components/ui/ConfirmDialog.vue', () => slots('ConfirmDialog'))
vi.mock('@/components/ListViews/EmptyState.vue', () => slots('EmptyState'))
vi.mock('@/components/ui/ErrorState.vue', () => slots('ErrorState'))
vi.mock('@/components/ui/Skeleton.vue', () => slots('Skeleton'))
vi.mock('@/components/Planner/TeamWeek.vue', () => slots('TeamWeek'))
vi.mock('vue-router', () => ({ onBeforeRouteLeave: () => {} }))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'mgr@x' }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (name) => ({ full_name: name }) }),
}))
vi.mock('@/stores/settings', () => ({
  getSettings: () => ({ _settings: { doc: { lock_past_plans: 0 } } }),
}))
vi.mock('@/utils/renderFieldLayoutDialog', () => ({
  renderFieldLayoutDialog: async () => ui.dialog?.(),
}))

const ME = 'mgr@x'
const W0 = mondayOf(todayInTimeZone())
const W1 = addDays(W0, 7)
const W2 = addDays(W0, 14)

function week(week_start, items = [], user = ME, modified = null) {
  return {
    name: items.length ? 1 : null,
    week_start,
    user,
    modified,
    items,
    rollup: items.length
      ? {
          Visit: {
            planned: items.length,
            done: items.filter((i) => i.status === 'Done').length,
            missed: items.filter((i) => i.status === 'Missed').length,
            cancelled: 0,
          },
        }
      : {},
  }
}

function item(name, planned_date, note, status = 'Planned') {
  return {
    name,
    activity_type: 'Visit',
    planned_date,
    note,
    status,
    organization: null,
    reference_doctype: null,
    reference_docname: null,
    suggestion: null,
    outcome: null,
    manual_override: 0,
    fulfilled_by_doctype: null,
    fulfilled_by: null,
  }
}

const Button = {
  name: 'Button',
  inheritAttrs: false,
  render() {
    const a = this.$attrs
    return h(
      'button',
      {
        'data-label': a.label,
        disabled: a.disabled || undefined,
        onClick: a.onClick,
      },
      this.$slots.default?.(),
    )
  },
}
const RouterLink = {
  name: 'RouterLink',
  render() {
    return h('a', this.$slots.default?.())
  },
}

async function flush() {
  for (let i = 0; i < 6; i++) {
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

function answer(entry, data) {
  entry.done = true
  entry.resolve(data)
}

function getPlan(when = () => true) {
  return net.requests.find(
    (r) => !r.done && r.url === 'crm.api.rep_plan.get_plan' && when(r.params),
  )
}

function callTo(method) {
  return net.calls.find(
    (c) => !c.done && c.method === `crm.api.rep_plan.${method}`,
  )
}

const text = (el) => el.textContent.replace(/\s+/g, ' ')
const button = (el, label) => el.querySelector(`button[data-label="${label}"]`)
const card = (el, note) =>
  [...el.querySelectorAll('[data-plan-uid]')].find((c) =>
    c.textContent.includes(note),
  )

async function open(first = week(W0), reps = []) {
  const wrapper = mount(Planner, { stubs: { Button, RouterLink } })
  const visible = net.requests.find(
    (r) => r.url === 'crm.api.rep_plan.get_visible_reps',
  )
  answer(visible, reps)
  answer(getPlan(), first)
  await flush()
  return wrapper.el
}

beforeEach(() => {
  net.requests.length = 0
  net.calls.length = 0
  ui.selects = {}
  ui.dialog = null
})

afterEach(() => vi.clearAllMocks())

describe('Planner only shows answers for the week and rep on screen', () => {
  it('drops a week that answers after the one asked for next', async () => {
    const el = await open()
    button(el, 'Next week').click()
    await flush()
    button(el, 'Next week').click()
    await flush()

    answer(
      getPlan((p) => p.week_start === W2),
      week(W2),
    )
    await flush()
    answer(
      getPlan((p) => p.week_start === W1),
      week(W1, [item(11, addDays(W1, 1), 'Visit at Sasol', 'Done')]),
    )
    await flush()

    expect(text(el)).toContain('0 planned')
    expect(text(el)).not.toContain('Visit at Sasol')
    expect(text(el)).not.toMatch(/fall outside this week/)
  })

  it("never shows another rep's plan as the manager's own", async () => {
    const el = await open(week(W0), ['alice@x'])
    const pick = ui.selects['Whose plan to show']['onUpdate:modelValue']
    pick('alice@x')
    await flush()
    pick(ME)
    await flush()

    answer(
      getPlan((p) => p.user === ME),
      week(W0),
    )
    await flush()
    answer(
      getPlan((p) => p.user === 'alice@x'),
      week(
        W0,
        [item(21, addDays(W0, 2), "Alice's quote follow-up")],
        'alice@x',
      ),
    )
    await flush()

    expect(text(el)).not.toContain("Alice's quote follow-up")
  })

  it('does not merge a correction answered after moving to another week', async () => {
    const transnet = item(5, addDays(W0, 3), 'Call Transnet')
    const el = await open(week(W0, [transnet]))
    card(el, 'Call Transnet')
      .querySelector('button[data-label="Mark as missed"]')
      .click()
    await flush()
    button(el, 'Next week').click()
    await flush()
    answer(
      getPlan((p) => p.week_start === W1),
      week(W1),
    )
    await flush()

    answer(
      callTo('mark_missed'),
      week(W0, [{ ...transnet, status: 'Missed', manual_override: 1 }]),
    )
    await flush()

    expect(text(el)).toContain('0 planned')
    expect(text(el)).not.toMatch(/\d+ unsaved/)
  })
})

describe('Planner logging an activity', () => {
  it('appends only the logged row, not one the user removed and has not saved', async () => {
    const kept = item(6, addDays(W0, 1), 'Visit Eskom')
    const removed = item(7, addDays(W0, 3), 'Call Transnet')
    const el = await open(week(W0, [kept, removed], ME, '2026-10-03 08:00:00'))
    card(el, 'Call Transnet')
      .querySelector('button[data-label="Remove from plan"]')
      .click()
    await flush()
    expect(text(el)).not.toContain('Call Transnet')
    expect(text(el)).toMatch(/1 unsaved/)

    ui.dialog = () => ({
      activity_type: 'Call',
      note: 'Sasol rang about a breakdown',
    })
    button(el, 'Log activity').click()
    await flush()
    const logged = {
      ...item(8, addDays(W0, 2), 'Sasol rang about a breakdown', 'Done'),
      activity_type: 'Call',
      manual_override: 1,
    }
    answer(
      callTo('log_unplanned_visit'),
      week(W0, [kept, removed, logged], ME, '2026-10-03 09:00:01'),
    )
    await flush()

    expect(text(el)).toContain('Sasol rang about a breakdown')
    expect(text(el)).not.toContain('Call Transnet')
    expect(text(el)).toMatch(/1 unsaved/)
  })
})

describe('Planner while a save is in flight', () => {
  it('takes no edit the save would then overwrite', async () => {
    const el = await open()
    ui.dialog = () => ({
      activity_type: 'Visit',
      planned_date: addDays(W0, 1),
      note: 'Visit Eskom',
    })
    button(el, 'Add an activity').click()
    await flush()
    button(el, 'Save plan').click()
    await flush()

    // nothing on the grid can be changed until the save has landed
    expect(button(el, 'Add an activity')).toBeNull()
    expect(card(el, 'Visit Eskom').getAttribute('draggable')).toBe('false')
    expect(button(el, 'Log activity').disabled).toBe(true)

    const save = callTo('save_plan')
    answer(
      save,
      week(
        W0,
        [{ ...item(100, addDays(W0, 1), 'Visit Eskom') }],
        ME,
        '2026-10-04 12:00:00',
      ),
    )
    await flush()

    expect(text(el)).toContain('Visit Eskom')
    expect(text(el)).not.toMatch(/\d+ unsaved/)
    expect(button(el, 'Add an activity')).not.toBeNull()
  })
})
