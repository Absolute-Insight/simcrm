import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, reactive } from 'vue'
import { mount } from './mount.js'

// The real Link.vue and frappe-ui createResource; Autocomplete is stubbed with
// the `query` it exposes, and renders the options it is given.
const queries = vi.hoisted(() => [])
vi.mock('@/components/frappe-ui/Autocomplete.vue', async () => {
  const { defineComponent, h, ref } = await import('vue')
  return {
    default: defineComponent({
      props: { options: { type: Array, default: null } },
      setup(props, { expose }) {
        const query = ref('')
        queries.push(query)
        expose({ query })
        return () =>
          h('div', {
            class: 'ac',
            'data-options': (props.options || []).map((o) => o.value).join(','),
          })
      },
    }),
  }
})

const { setConfig } = await import('frappe-ui')
const requests = []
setConfig('resourceFetcher', async ({ params }) => {
  requests.push(params)
  const txt = params.txt || ''
  return txt
    ? [{ value: `${txt.toUpperCase()}-1` }, { value: `${txt.toUpperCase()}-2` }]
    : [{ value: 'PUMP-1' }, { value: 'VALVE-1' }]
})

const Link = (await import('@/components/Controls/Link.vue')).default

// Past the 300ms search debounce.
const settle = () => new Promise((resolve) => setTimeout(resolve, 350))

function rows(n, state) {
  return mount(
    defineComponent({
      setup: () => () =>
        Array.from({ length: n }, (_, i) =>
          h(Link, {
            key: i,
            doctype: state.doctype,
            // A fresh array on every render, as an inline binding gives.
            filters: [...state.filters],
            value: '',
            onChange: () => {},
          }),
        ),
    }),
  )
}
const shown = (el) =>
  [...el.querySelectorAll('.ac')].map((d) => d.dataset.options)

describe('Link', () => {
  it('sends one search per Link on mount', async () => {
    requests.length = 0
    const w = rows(3, { doctype: 'CRM Product', filters: [] })
    await settle()
    expect(requests).toHaveLength(3)
    expect(shown(w.el)).toEqual(Array(3).fill('PUMP-1,VALVE-1'))
    w.unmount()
  })

  it("text typed in one Link does not change another's options", async () => {
    queries.length = 0
    const w = rows(2, { doctype: 'CRM Organization', filters: [] })
    await settle()
    queries[0].value = 'acme'
    await settle()
    await nextTick()
    expect(shown(w.el)).toEqual(['ACME-1,ACME-2', 'PUMP-1,VALVE-1'])
    w.unmount()
  })

  it('searches again when the filters change, not when they are re-rendered', async () => {
    const state = reactive({ doctype: 'CRM Product', filters: [] })
    const w = rows(1, state)
    await settle()
    requests.length = 0

    w.vm.$forceUpdate() // a parent re-render: new filters array, same content
    await settle()
    expect(requests).toHaveLength(0)

    state.filters = [['disabled', '=', 0]]
    await settle()
    expect(requests).toHaveLength(1)
    expect(JSON.parse(JSON.stringify(requests[0].filters))).toEqual([
      ['disabled', '=', 0],
    ])
    w.unmount()
  })
})
