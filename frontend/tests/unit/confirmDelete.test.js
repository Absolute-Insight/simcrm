import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'

// utils/index.js pulls in SFCs and stores that vitest cannot compile; stub
// them so the pure helpers under test can load.
vi.mock('@/components/Icon.vue', () => ({ default: {} }))
vi.mock('@/components/Icons/TaskStatusIcon.vue', () => ({ default: {} }))
vi.mock('@/components/Icons/TaskPriorityIcon.vue', () => ({ default: {} }))
vi.mock('@/stores/users', () => ({ usersStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('frappe-ui', () => ({
  toast: {},
  dayjsLocal: () => ({}),
  dayjs: () => ({}),
  getConfig: () => undefined,
}))

const { ConfirmDelete } = await import('@/utils')

// frappe-ui 1.0's Menu drops `component:` rows to a plain label and calls only
// the option's own onClick, so every handler has to live on the option itself.
// The first click must keep the menu open (reka closes it unless the select
// event is default-prevented) or the confirm row is never seen.
function visible(options) {
  return options.filter((o) => (o.condition ? o.condition() : true))
}

function selectEvent() {
  return new CustomEvent('menu.itemSelect', { cancelable: true })
}

describe('ConfirmDelete', () => {
  it('puts the handlers on the options, not in a component', () => {
    const options = ConfirmDelete({
      isConfirmingDelete: ref(false),
      onConfirmDelete: () => {},
    })
    for (const option of options) {
      expect(option.component).toBeUndefined()
      expect(option.onClick).toBeTypeOf('function')
    }
  })

  it('asks before deleting, keeping the menu open between the two clicks', () => {
    const confirming = ref(false)
    const onConfirmDelete = vi.fn()
    const options = ConfirmDelete({
      isConfirmingDelete: confirming,
      onConfirmDelete,
      label: 'Remove',
    })

    const [first] = visible(options)
    expect(first.label).toBe('Remove')
    const event = selectEvent()
    first.onClick(event)
    expect(event.defaultPrevented).toBe(true)
    expect(onConfirmDelete).not.toHaveBeenCalled()

    const [second] = visible(options)
    expect(second.label).toBe('Confirm Remove')
    expect(second.theme).toBe('red')
    second.onClick(selectEvent())
    expect(onConfirmDelete).toHaveBeenCalledOnce()
    expect(confirming.value).toBe(false)
  })
})
