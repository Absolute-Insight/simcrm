/**
 * pages/Dashboard.vue against frappe-ui's real createResource, fed by a fake
 * network the test answers (and re-orders) itself. Child panels, stores and
 * the filter widgets are stubs that record the props they were rendered with,
 * which is what the page's own logic decides.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount } from './mount.js'

const fp = vi.hoisted(() => ({
  role: 'manager',
  children: {},
  requests: [],
  drills: [],
  opened: 0,
  respond: null,
}))

/** A component that renders its slots and records its props. */
const recorder = vi.hoisted(() => (name, tag = 'div') => async () => {
  const { defineComponent, h } = await import('vue')
  return defineComponent({
    name,
    inheritAttrs: false,
    setup(_, { attrs, slots }) {
      ;(fp.children[name] ||= []).push(attrs)
      return () =>
        h(tag, { 'data-stub': name, 'data-label': attrs.label ?? '' }, [
          attrs.label != null ? String(attrs.label) : null,
          slots['left-header']?.(),
          slots['right-header']?.(),
          slots.actions?.(),
          slots.default?.(),
        ])
    },
  })
})

vi.mock('frappe-ui', async (importOriginal) => {
  const actual = await importOriginal()
  const stub = async (name) => ({ [name]: await recorder(name)() })
  const picker = await recorder('DateRangePicker')()
  return {
    ...actual,
    ...(await stub('Badge')),
    // Custom Range opens the picker through its ref
    DateRangePicker: {
      ...picker,
      setup(props, context) {
        context.expose({ open: () => fp.opened++ })
        return picker.setup(props, context)
      },
    },
    ...(await stub('Dropdown')),
    ...(await stub('Select')),
    usePageMeta: () => {},
  }
})
const stubbed = vi.hoisted(() => (name) => async () => ({
  default: await recorder(name)(),
}))
vi.mock('@/components/Dashboard/AddChartModal.vue', stubbed('AddChartModal'))
vi.mock('@/components/Dashboard/DashboardItem.vue', stubbed('DashboardItem'))
vi.mock('@/components/Dashboard/DashboardGrid.vue', stubbed('DashboardGrid'))
vi.mock('@/components/Dashboard/PanelCard.vue', stubbed('PanelCard'))
vi.mock('@/components/Dashboard/RadialGauge.vue', stubbed('RadialGauge'))
vi.mock('@/components/Dashboard/StatTile.vue', stubbed('StatTile'))
vi.mock('@/components/ListViews/EmptyState.vue', stubbed('EmptyState'))
vi.mock('@/components/ui/ErrorState.vue', stubbed('ErrorState'))
vi.mock('@/components/ui/SkeletonTable.vue', stubbed('SkeletonTable'))
vi.mock('@/components/ViewBreadcrumbs.vue', stubbed('ViewBreadcrumbs'))
vi.mock('@/components/LayoutHeader.vue', stubbed('LayoutHeader'))
vi.mock('@/components/Controls/Link.vue', stubbed('Link'))
vi.mock('@/components/Dashboard/drilldown', () => ({
  useDrilldown: () => ({
    drillInto: (...args) => fp.drills.push(args),
    canDrillInto: () => true,
  }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: () => {} }) }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    getUser: (name) => ({ name, full_name: name }),
    isManager: () => fp.role === 'manager',
    isAdmin: () => false,
  }),
}))
vi.mock('@/composables/visibleReps', async () => {
  const { ref } = await import('vue')
  return {
    ALL_REPS: '__all__',
    useVisibleReps: () => ({ filterOptions: ref([]) }),
  }
})
vi.mock('@/stores/settings', async () => {
  const { ref } = await import('vue')
  return {
    getSettings: () => ({ settings: ref({ currency: 'ZAR' }), brand: {} }),
  }
})
vi.mock('@/composables/settings', async () => {
  const { ref } = await import('vue')
  return { isNarrowGrid: ref(false) }
})
vi.mock('@/stores/suggestions', async () => {
  const { reactive } = await import('vue')
  return {
    suggestions: reactive({
      data: [],
      loading: false,
      error: null,
      reload: () => Promise.resolve(),
    }),
    referenceLabels: reactive({}),
  }
})

import { setConfig } from 'frappe-ui'
import Dashboard from '@/pages/Dashboard.vue'

const later = (value) => new Promise((r) => setTimeout(() => r(value), 1))
const copy = (value) => JSON.parse(JSON.stringify(value))

function defaultResponse(url) {
  if (url === 'crm.api.dashboard.get_dashboard') return later([])
  if (url === 'crm.api.reports.get_report') return later({ rows: [] })
  if (url === 'crm.api.rep_plan.get_plan') return later({ items: [] })
  return later({ value: 0 })
}

setConfig('resourceFetcher', (options) => {
  const params = copy(options.params ?? null)
  fp.requests.push({ url: options.url, params })
  return (fp.respond || defaultResponse)(options.url, params)
})

const Button = defineComponent({
  name: 'ButtonStub',
  inheritAttrs: false,
  setup(_, { attrs }) {
    ;(fp.children.Button ||= []).push(attrs)
    return () =>
      h(
        'button',
        { 'data-label': attrs.label ?? '', onClick: attrs.onClick },
        attrs.label,
      )
  },
})
const Icon = defineComponent({ render: () => h('i') })

function mountDashboard() {
  return mount(Dashboard, {
    stubs: { Button, LucideCalendar: Icon, LucideMapPin: Icon },
  })
}

async function settle(rounds = 8) {
  for (let i = 0; i < rounds; i++) {
    await new Promise((r) => setTimeout(r, 3))
    await nextTick()
  }
}

const latest = (name) => fp.children[name]?.at(-1)
const sent = (url, since = 0) =>
  fp.requests.slice(since).filter((r) => r.url === url)
const choosePreset = (days) =>
  latest('Dropdown')
    .options[0].options.find((o) => o.label === `Last ${days} Days`)
    .onClick()
const click = (el, label) => el.querySelector(`[data-label="${label}"]`).click()

beforeEach(() => {
  Object.assign(fp, {
    role: 'manager',
    children: {},
    requests: [],
    drills: [],
    opened: 0,
    respond: null,
  })
  setConfig('systemTimezone', 'Africa/Johannesburg')
})

describe('Dashboard, as a manager', () => {
  it('refetches every team panel when the period changes', async () => {
    const { el } = mountDashboard()
    await settle()
    const panels = (since) =>
      sent('crm.api.reports.get_report', since)
        .map((r) => r.params.name)
        .sort()
    const atMount = panels(0)
    expect(atMount).toContain('rep_summary')
    expect(atMount).toContain('activities_by_type')

    const mark = fp.requests.length
    choosePreset(7)
    await settle()
    // Rep summary and Activity summary kept the first load's figures
    expect(panels(mark)).toEqual(atMount)

    const refresh = fp.requests.length
    click(el, 'Refresh')
    await settle()
    expect(panels(refresh)).toEqual(atMount)
  })

  it('shows the latest selection whatever order the answers land in', async () => {
    mountDashboard()
    await settle()
    const held = []
    fp.respond = (url, params) =>
      url === 'crm.api.dashboard.get_chart'
        ? new Promise((resolve) =>
            held.push({
              params,
              answer: () =>
                resolve({ value: `${params.from_date}..${params.to_date}` }),
            }),
          )
        : defaultResponse(url)

    choosePreset(90)
    choosePreset(7) // changed their mind before the 90-day query returned
    const sevenFrom = held.at(-1).params.from_date
    const seven = held.filter((x) => x.params.from_date === sevenFrom)
    const ninety = held.filter((x) => x.params.from_date !== sevenFrom)
    expect(ninety.length).toBeGreaterThan(0)

    seven.forEach((x) => x.answer())
    await settle()
    ninety.forEach((x) => x.answer()) // the slow query lands last
    await settle()

    const expected = `${seven[0].params.from_date}..${seven[0].params.to_date}`
    for (const tile of ['StatTile', 'RadialGauge']) {
      expect(latest(tile).value).toBe(expected)
    }
    expect(latest('Dropdown').button.label).toBe('Last 7 Days')
  })

  it('falls back to the last 30 days when the period is cleared', async () => {
    mountDashboard()
    await settle()
    latest('Dropdown').options[0].options.at(0).onClick() // Last 7 Days
    await settle()
    const mark = fp.requests.length

    // frappe-ui v1's DateRangePicker clears to [], not '' or null
    latest('DateRangePicker').onChange([])
    await settle()

    expect(latest('Dropdown').button.label).toBe('Last 30 Days')
    const tile = sent('crm.api.dashboard.get_chart', mark)[0]
    expect(tile.params.from_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(tile.params.to_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('treats a half-typed range as no range', async () => {
    mountDashboard()
    await settle()
    latest('DateRangePicker').onChange(['2026-10-01', ''])
    await settle()
    expect(latest('Dropdown').button.label).toBe('Last 30 Days')
  })

  /* frappe-ui's DateRangePicker emits nothing when it closes without a full
     range, so a Custom Range dismissed unpicked never reached onPeriodChange:
     the period it had nulled stayed null, and every later reload sent null
     dates, which the server answers with the current calendar month. */
  it('keeps the period when Custom Range is dismissed without one', async () => {
    const { el } = mountDashboard()
    await settle()
    choosePreset(7)
    await settle()
    const seven = sent('crm.api.dashboard.get_chart').at(-1).params

    latest('Dropdown').options.at(-1).onClick() // Custom Range
    await settle()
    expect(fp.opened).toBe(1)

    // dismissed: no change event, then a reload for some other reason
    const mark = fp.requests.length
    click(el, 'Refresh')
    await settle()

    const tile = sent('crm.api.dashboard.get_chart', mark)[0]
    expect(tile.params.from_date).toBe(seven.from_date)
    expect(tile.params.to_date).toBe(seven.to_date)
    expect(latest('Dropdown').button.label).toBe('Last 7 Days')
  })

  /* The closing Dropdown gives focus back to its trigger a tick or two later,
     and focus leaving the picker's popover dismisses it. */
  it('opens the Custom Range picker only once the menu has let go of focus', async () => {
    mountDashboard()
    await settle()
    const menu = document.createElement('div')
    menu.setAttribute('role', 'menu')
    menu.tabIndex = -1
    const trigger = document.createElement('button')
    document.body.append(menu, trigger)
    menu.focus()

    latest('Dropdown').options.at(-1).onClick() // Custom Range
    await settle()
    expect(fp.opened).toBe(0)

    trigger.focus()
    await settle()
    expect(fp.opened).toBe(1)
    menu.remove()
    trigger.remove()
  })

  it('drills into a tile with the chosen territory', async () => {
    mountDashboard()
    await settle()
    latest('Link').onChange('Gauteng')
    await settle()
    latest('StatTile').onDrill()
    const [, context] = fp.drills[0]
    expect(context).toMatchObject({ territory: 'Gauteng' })
  })

  it('keeps an unsaved arrangement when a filter changes mid-edit', async () => {
    const layout = (params) => [
      {
        name: 'sales_trend',
        type: 'axis_chart',
        layout: { x: 0, y: 0, w: 10, h: 9, i: 'sales_trend' },
        data: { period: `${params.from_date}..${params.to_date}` },
      },
    ]
    fp.respond = (url, params) =>
      url === 'crm.api.dashboard.get_dashboard'
        ? later(layout(params))
        : defaultResponse(url)
    const { el } = mountDashboard()
    await settle()
    click(el, 'Edit')
    await settle()

    // what a drag does: DashboardGrid writes the new layout through v-model
    const moved = copy(latest('DashboardGrid').modelValue)
    moved[0].layout.x = 10
    latest('DashboardGrid')['onUpdate:modelValue'](moved)
    await settle()
    expect(
      fp.children.Button.findLast((b) => b.label === 'Save').disabled,
    ).toBe(false)

    const mark = fp.requests.length
    choosePreset(90) // the filter bar stays live while editing
    await settle()
    const asked = sent('crm.api.dashboard.get_dashboard', mark)[0].params
    const ninety = `${asked.from_date}..${asked.to_date}`

    const grid = latest('DashboardGrid').modelValue
    expect(grid[0].layout.x).toBe(10) // the arrangement survived...
    expect(grid[0].data.period).toBe(ninety) // ...under the new figures
    expect(
      fp.children.Button.findLast((b) => b.label === 'Save').disabled,
    ).toBe(false)

    // Cancel goes back to the saved arrangement, not to the old period
    click(el, 'Cancel')
    await settle()
    const restored = latest('DashboardGrid').modelValue
    expect(restored[0].layout.x).toBe(0)
    expect(restored[0].data.period).toBe(ninety)
  })
})

describe('Dashboard, as a rep', () => {
  beforeEach(() => {
    fp.role = 'rep'
  })

  it('never asks the server for the manager grid or team-only tiles', async () => {
    const { el } = mountDashboard()
    await settle()
    expect(el.querySelector('[data-stub="DashboardGrid"]')).toBeNull()
    const mark = fp.requests.length
    click(el, 'Refresh')
    await settle()

    expect(sent('crm.api.dashboard.get_dashboard')).toEqual([])
    const leads = sent('crm.api.dashboard.get_chart', mark).filter(
      (r) => r.params.name === 'total_leads',
    )
    expect(leads).toEqual([])
    // the tiles a rep does see still refresh
    expect(
      sent('crm.api.dashboard.get_chart', mark).map((r) => r.params.name),
    ).toContain('won_deals')
  })

  describe("today's plan", () => {
    const PLANS = {
      '2026-10-26': [
        {
          name: 'a',
          planned_date: '2026-11-01',
          note: 'SUNDAY-ADMIN',
          status: 'Done',
          activity_type: 'Admin',
        },
      ],
      '2026-11-02': [
        {
          name: 'b',
          planned_date: '2026-11-02',
          note: 'MONDAY-VISIT-1',
          status: 'Planned',
          activity_type: 'Visit',
        },
      ],
    }
    const weeksAsked = (since = 0) =>
      sent('crm.api.rep_plan.get_plan', since).map((r) => r.params.week_start)

    beforeEach(() => {
      vi.useFakeTimers({ toFake: ['Date'] })
      fp.respond = (url, params) =>
        url === 'crm.api.rep_plan.get_plan'
          ? later({ items: PLANS[params.week_start] || [] })
          : defaultResponse(url)
    })
    afterEach(() => {
      vi.useRealTimers()
      vi.unstubAllEnvs()
    })

    it('moves to the new day on Refresh after midnight', async () => {
      vi.stubEnv('TZ', 'Africa/Johannesburg')
      vi.setSystemTime(new Date('2026-11-01T21:30:00Z')) // Sunday 23:30 SAST
      const { el } = mountDashboard()
      await settle()
      expect(el.textContent).toContain('SUNDAY-ADMIN')

      vi.setSystemTime(new Date('2026-11-02T06:00:00Z')) // Monday 08:00, same tab
      const mark = fp.requests.length
      click(el, 'Refresh')
      await settle()

      expect(weeksAsked(mark)).toEqual(['2026-11-02'])
      expect(el.textContent).toContain('MONDAY-VISIT-1')
      expect(el.textContent).not.toContain('SUNDAY-ADMIN')
    })

    it("asks for the site's week, not the browser's", async () => {
      // Monday 01:30 in Johannesburg is still Sunday evening in London
      vi.stubEnv('TZ', 'Europe/London')
      vi.setSystemTime(new Date('2026-11-01T23:30:00Z'))
      const { el } = mountDashboard()
      await settle()

      expect(weeksAsked()).toEqual(['2026-11-02'])
      expect(el.textContent).toContain('MONDAY-VISIT-1')
    })
  })
})
