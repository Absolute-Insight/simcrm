import { afterEach, describe, expect, it, vi } from 'vitest'
import { reactive, ref } from 'vue'
import { TextInput } from 'frappe-ui'
import { mount } from './mount.js'
import SlaPolicyList from '@/components/Settings/Sla/SlaPolicyList.vue'

const policies = [
  'Gold Support',
  ...Array.from({ length: 11 }, (_, i) => `Policy ${i + 1}`),
].map((name) => ({ name, default: 0, enabled: 1, apply_on: 'CRM Lead' }))

function mountList() {
  // SlaConfig owns the resource and the query and provides them; the list
  // only reads and writes them.
  const resource = reactive({
    data: policies,
    list: { loading: false, data: policies },
    filters: {},
    start: 0,
    pageLength: 999,
    reload: vi.fn(),
  })
  const query = ref('')
  const wrapper = mount(SlaPolicyList, {
    // main.js registers TextInput globally; the list relies on that
    stubs: { TextInput },
    plugins: [
      {
        install(app) {
          app.provide('slaPolicyListResource', resource)
          app.provide('slaSearchQuery', query)
          app.provide('updateStep', vi.fn())
        },
      },
    ],
  })
  return { wrapper, resource, query }
}

const search = (el) => el.querySelector('input[placeholder="Search"]')

async function type(el, text) {
  const input = search(el)
  input.value = text
  input.dispatchEvent(new InputEvent('input', { bubbles: true }))
  await vi.advanceTimersByTimeAsync(400) // past the 300ms debounce
}

describe('SLA policy search', () => {
  afterEach(() => vi.useRealTimers())

  // frappe-ui v1's TextInput hands unknown listeners to the native <input>,
  // so `@input="slaSearchQuery = $event"` stored the InputEvent: the filter
  // read "%[object InputEvent]%", nothing matched, and with the query no
  // longer a string the box itself disappeared.
  it('filters on the text typed and keeps the box on screen', async () => {
    vi.useFakeTimers()
    const { wrapper, resource, query } = mountList()

    await type(wrapper.el, 'gold')

    expect(query.value).toBe('gold')
    expect(resource.filters).toEqual({ name: ['like', '%gold%'] })
    expect(resource.reload).toHaveBeenCalled()
    await wrapper.nextTick()
    expect(search(wrapper.el)).not.toBeNull()
    wrapper.unmount()
  })

  // Clearing used to set pageLength to 10 on the module-cached resource,
  // which SlaConfig created with 999, so the full list came back cut short.
  it('clearing the search brings the whole list back', async () => {
    vi.useFakeTimers()
    const { wrapper, resource, query } = mountList()

    await type(wrapper.el, 'gold')
    await type(wrapper.el, '')

    expect(query.value).toBe('')
    expect(resource.start).toBe(0)
    expect(resource.pageLength).toBe(999)
    wrapper.unmount()
  })
})
