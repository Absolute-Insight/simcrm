/**
 * DashboardGrid + the vendored GridLayout + the real grid-layout-plus.
 *
 * Narrow screens are handled by `isNarrowGrid` (the viewport), which stacks
 * panels without touching their layout. The grid itself must never re-lay
 * them out by its own width: at a 1024px window with the sidebar open it is
 * ~720px wide, and a breakpoint re-layout written into the items is what
 * Save then persists for the whole site.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import { mount } from './mount.js'

vi.mock('@/composables/settings', async () => {
  const { ref } = await import('vue')
  return { isNarrowGrid: ref(false) } // a viewport of at least 1000px
})
vi.mock('@/components/Dashboard/DashboardItem.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent({ render: () => h('i') }) }
})

import DashboardGrid from '@/components/Dashboard/DashboardGrid.vue'

const offsetWidth = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  'offsetWidth',
)
afterEach(() => {
  if (offsetWidth) {
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', offsetWidth)
  }
})

/** Render the grid at `px` wide and return what it left in the items. */
async function layoutAt(px) {
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    get() {
      return this.classList?.contains('vgl-layout') ? px : 0
    },
  })
  // two panels the way default_manager_dashboard_layout places them
  const items = reactive([
    {
      name: 'sales_trend',
      type: 'axis_chart',
      layout: { x: 0, y: 0, w: 10, h: 7, i: 'sales_trend' },
    },
    {
      name: 'average_won_deal_value',
      type: 'number_chart',
      layout: { x: 10, y: 0, w: 4, h: 2, i: 'average_won_deal_value' },
    },
  ])
  mount(DashboardGrid, {
    props: { modelValue: items, editing: false },
  })
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 5))
    await nextTick()
  }
  return items.map((item) => [item.layout.x, item.layout.w])
}

describe('DashboardGrid', () => {
  it('leaves the stored layout alone on a wide grid', async () => {
    expect(await layoutAt(1100)).toEqual([
      [0, 10],
      [10, 4],
    ])
  })

  it('does not collapse the stored layout to one column on a ~720px grid', async () => {
    expect(await layoutAt(719)).toEqual([
      [0, 10],
      [10, 4],
    ])
  })
})
