/**
 * pages/Reports.vue against frappe-ui's real createResource. Every request
 * parks until the test answers it, so the test decides the order responses
 * land in -- the thing a real network does to two quick selections.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'

const fp = vi.hoisted(() => ({ requests: [], selects: {} }))

const recorder = vi.hoisted(() => (name) => async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      name,
      inheritAttrs: false,
      setup:
        (_, { slots }) =>
        () =>
          h('div', { 'data-stub': name }, [
            slots['left-header']?.(),
            slots['right-header']?.(),
            slots.default?.(),
          ]),
    }),
  }
})

vi.mock('frappe-ui', async (importOriginal) => {
  const actual = await importOriginal()
  const { defineComponent, h } = await import('vue')
  const widget = (name) =>
    defineComponent({
      name,
      inheritAttrs: false,
      setup(_, { attrs, slots }) {
        if (name === 'Select') fp.selects[attrs['aria-label']] = attrs
        return () => h('div', { 'data-stub': name }, slots.default?.())
      },
    })
  return {
    ...actual,
    DateRangePicker: widget('DateRangePicker'),
    Dropdown: widget('Dropdown'),
    Select: widget('Select'),
    Tooltip: widget('Tooltip'),
    usePageMeta: () => {},
  }
})
vi.mock('@/components/ListViews/EmptyState.vue', recorder('EmptyState'))
vi.mock('@/components/LayoutHeader.vue', recorder('LayoutHeader'))
vi.mock('@/components/Controls/Link.vue', recorder('Link'))
vi.mock('@/components/ui/ErrorState.vue', recorder('ErrorState'))
vi.mock('@/components/ui/Skeleton.vue', recorder('Skeleton'))
vi.mock('@/components/ui/SkeletonTable.vue', recorder('SkeletonTable'))
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  return {
    useRoute: () => reactive({ name: 'Reports', params: {}, query: {} }),
    useRouter: () => ({
      push: () => {},
      replace: () => {},
      resolve: () => ({ href: '/crm/reports' }),
    }),
  }
})
vi.mock('@/stores/settings', async () => {
  const { ref } = await import('vue')
  return { getSettings: () => ({ settings: ref({ currency: 'ZAR' }) }) }
})
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ isManager: () => true, isAdmin: () => false }),
}))
vi.mock('@/composables/visibleReps', async () => {
  const { computed } = await import('vue')
  return {
    ALL_REPS: '__all__',
    useVisibleReps: () => ({
      filterOptions: computed(() => [
        { label: 'All reps', value: '__all__' },
        { label: 'Alice', value: 'alice@x' },
      ]),
    }),
  }
})

import { setConfig } from 'frappe-ui'
import Reports from '@/pages/Reports.vue'

setConfig('resourceFetcher', (options) => {
  let resolve
  const promise = new Promise((r) => (resolve = r))
  fp.requests.push({
    url: options.url,
    params: JSON.parse(JSON.stringify(options.params ?? null)),
    resolve,
    done: false,
  })
  return promise
})

afterEach(() => {
  fp.requests.length = 0
  fp.selects = {}
})

const pending = (url, match = () => true) =>
  fp.requests.filter((r) => r.url === url && !r.done && match(r.params || {}))
const answer = (request, data) => {
  request.done = true
  request.resolve(data)
}
async function flush(rounds = 6) {
  for (let i = 0; i < rounds; i++) {
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))
  }
}

const COLUMNS = [
  { key: 'rep', label: 'Rep', type: 'text' },
  { key: 'visits', label: 'Visits', type: 'number' },
]
const payload = (title, rows) => ({
  name: 'x',
  title,
  description: '',
  period: true,
  columns: COLUMNS,
  rows,
  notice: null,
  territory: null,
  territory_filtered: false,
})
const heading = (el) => el.querySelector('h2')?.textContent.trim()
const cells = (el) =>
  [...el.querySelectorAll('tbody td')].map((td) => td.textContent.trim())

async function openReports() {
  const { el } = mount(Reports, {
    stubs: { Button: { render: () => null } },
  })
  answer(pending('crm.api.report_builder.get_builder_options')[0], {
    dimensions: [],
    measures: [],
    status_scopes: [],
  })
  answer(pending('crm.api.reports.list_reports')[0], [
    { name: 'visits_by_rep', title: 'Visits by rep', period: true },
    { name: 'rep_summary', title: 'Rep summary', period: true },
  ])
  await flush()
  return el
}

describe('Reports', () => {
  it('does not show a slower earlier report under the one chosen since', async () => {
    const el = await openReports()
    const first = pending('crm.api.reports.get_report')[0]
    el.querySelector('#report-tab-rep_summary').click()
    await flush()
    const second = pending(
      'crm.api.reports.get_report',
      (p) => p.name === 'rep_summary',
    )[0]

    answer(second, payload('Rep summary', [{ rep: 'Alice', visits: 4 }]))
    await flush()
    expect(heading(el)).toBe('Rep summary')

    answer(first, payload('Visits by rep', [{ rep: 'All', visits: 999 }]))
    await flush()
    expect(heading(el)).toBe('Rep summary')
    expect(cells(el)).toEqual(['Alice', '4'])
  })

  it('does not show the all-reps rows under a rep chosen since', async () => {
    const el = await openReports()
    const allReps = pending('crm.api.reports.get_report')[0]
    fp.selects.Rep['onUpdate:modelValue']('alice@x')
    await flush()
    const alice = pending(
      'crm.api.reports.get_report',
      (p) => p.user === 'alice@x',
    )[0]

    answer(alice, payload('Visits by rep', [{ rep: 'Alice', visits: 4 }]))
    await flush()
    answer(
      allReps,
      payload('Visits by rep', [
        { rep: 'Alice', visits: 4 },
        { rep: 'Bob', visits: 11 },
      ]),
    )
    await flush()
    expect(cells(el)).toEqual(['Alice', '4'])
  })

  /* The two resources share one "loaded" stamp. A built-in report landing
     late stamped the builder's *current* selection as loaded, which put the
     builder's previous rows (by stage) under a newly chosen dimension. */
  it("does not let another resource's late answer vouch for stale rows", async () => {
    const el = await openReports()
    const builtIn = pending('crm.api.reports.get_report')[0]
    el.querySelector('#report-tab-__builder__').click()
    await flush()
    answer(
      pending('crm.api.report_builder.run')[0],
      payload('Deals by stage', [{ rep: 'Open', visits: 3 }]),
    )
    await flush()
    expect(heading(el)).toBe('Deals by stage')

    fp.selects.Dimension['onUpdate:modelValue']('industry')
    await flush()
    const byIndustry = pending('crm.api.report_builder.run')[0]
    expect(byIndustry.params.dimension).toBe('industry')

    // the built-in report lands while the builder's new request is still out
    answer(builtIn, payload('Visits by rep', [{ rep: 'All', visits: 999 }]))
    await flush()
    expect(heading(el)).toBeUndefined() // loading, not the stage rows

    answer(
      byIndustry,
      payload('Deals by industry', [{ rep: 'Mining', visits: 2 }]),
    )
    await flush()
    expect(heading(el)).toBe('Deals by industry')
  })

  /* A late answer from the resource no longer on screen stamped its own
     selection as loaded, which no longer matched the one chosen, and left the
     rows that did match behind a skeleton until a filter changed. */
  it('keeps the builder on screen when a built-in report lands after it', async () => {
    const el = await openReports()
    const builtIn = pending('crm.api.reports.get_report')[0]
    el.querySelector('#report-tab-__builder__').click()
    await flush()
    answer(
      pending('crm.api.report_builder.run')[0],
      payload('Deals by stage', [{ rep: 'Open', visits: 3 }]),
    )
    await flush()
    expect(heading(el)).toBe('Deals by stage')

    answer(builtIn, payload('Visits by rep', [{ rep: 'All', visits: 999 }]))
    await flush()
    expect(heading(el)).toBe('Deals by stage')
    expect(cells(el)).toEqual(['Open', '3'])
  })

  it('keeps a built-in report on screen when the builder lands after it', async () => {
    const el = await openReports()
    answer(
      pending('crm.api.reports.get_report')[0],
      payload('Visits by rep', [{ rep: 'All', visits: 999 }]),
    )
    await flush()
    el.querySelector('#report-tab-__builder__').click()
    await flush()
    const built = pending('crm.api.report_builder.run')[0]
    el.querySelector('#report-tab-rep_summary').click()
    await flush()
    answer(
      pending('crm.api.reports.get_report', (p) => p.name === 'rep_summary')[0],
      payload('Rep summary', [{ rep: 'Alice', visits: 4 }]),
    )
    await flush()
    expect(heading(el)).toBe('Rep summary')

    answer(built, payload('Deals by stage', [{ rep: 'Open', visits: 3 }]))
    await flush()
    expect(heading(el)).toBe('Rep summary')
    expect(cells(el)).toEqual(['Alice', '4'])
  })
})
