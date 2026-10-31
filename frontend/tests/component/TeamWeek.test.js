import { describe, expect, it, vi } from 'vitest'
import { h, nextTick, reactive } from 'vue'
import { mount } from './mount.js'
import TeamWeek from '@/components/Planner/TeamWeek.vue'

/* TeamWeek on frappe-ui's real createResource, with a fetcher that parks each
   request by week until the test answers it, so the test decides the order
   the responses land in. */
const { pending } = vi.hoisted(() => ({ pending: {} }))

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
  setConfig(
    'resourceFetcher',
    ({ params }) =>
      new Promise((resolve) => (pending[params.week_start] = resolve)),
  )
  return {
    createResource,
    getConfig,
    setConfig,
    dayjs,
    Select: { render: () => null },
  }
})

function teamWeek(week_start, dates, done) {
  return {
    week_start,
    reps: [
      {
        user: 'rep@x',
        full_name: 'Rep One',
        items: dates.map((date, i) => ({
          name: `${date}-${i}`,
          activity_type: 'Visit',
          status: i < done ? 'Done' : 'Planned',
          planned_date: date,
        })),
      },
    ],
  }
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

describe('TeamWeek', () => {
  it('shows the totals of the week in its header, whatever order the answers land in', async () => {
    const props = reactive({ weekStart: '2026-10-26', today: '2026-10-30' })
    // a parent that passes the current week down, as Planner does
    const w = mount({ render: () => h(TeamWeek, { ...props }) })
    pending['2026-10-26'](teamWeek('2026-10-26', ['2026-10-27'], 1))
    await settle()

    props.weekStart = '2026-11-02'
    await nextTick()
    props.weekStart = '2026-11-09'
    await nextTick()

    // the week asked for last answers first, the one before it last
    pending['2026-11-09'](teamWeek('2026-11-09', ['2026-11-10'], 0))
    await settle()
    pending['2026-11-02'](
      teamWeek('2026-11-02', ['2026-11-03', '2026-11-04', '2026-11-05'], 3),
    )
    await settle()

    const header = [...w.el.querySelectorAll('thead th span')].map((s) =>
      s.textContent.trim(),
    )
    expect(header[0]).toBe('Mon 9')
    expect(w.el.querySelector('span.tabular-nums').textContent.trim()).toBe(
      '1 planned · 0 done · 0 missed · 0 cancelled',
    )
    expect(w.el.textContent).toContain('0 of 1 done')
  })
})
