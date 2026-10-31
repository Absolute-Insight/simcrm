import { h, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import FieldLayoutEditor from '@/components/FieldLayoutEditor.vue'

// Every section menu the editor renders, in render order.
const S = vi.hoisted(() => ({ menus: [] }))

vi.mock('vuedraggable', async () => {
  const { h } = await import('vue')
  return {
    // vuedraggable's slot contract: #item gets { element, index }.
    default: {
      props: { list: Array },
      setup(props, { slots }) {
        return () =>
          h('div', [
            ...(props.list || []).map((element, index) =>
              slots.item?.({ element, index }),
            ),
            slots.footer?.(),
          ])
      },
    },
  }
})
vi.mock('frappe-ui', () => ({
  Dropdown: {
    props: { options: Array },
    setup(props) {
      return () => {
        if (props.options?.[0]?.group === 'Section') S.menus.push(props.options)
        return null
      }
    },
  },
  Combobox: { render: () => null },
}))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({ getFields: () => [] }) }))
vi.mock('@/stores/global', () => ({
  // Confirm every dialog.
  globalStore: () => ({ $dialog: (o) => o.actions[0].onClick({ close() {} }) }),
}))
vi.mock('@/components/Icons/DragVerticalIcon.vue', () => ({
  default: { render: () => null },
}))

const Button = {
  inheritAttrs: false,
  render() {
    return h('button', {
      'data-label': this.$attrs.label,
      onClick: this.$attrs.onClick,
    })
  },
}
const TextInput = { render: () => null }

const field = (name) => ({ fieldname: name, label: name.toUpperCase() })
const section = (n, fieldname) => ({
  name: 's' + n,
  label: 'Section ' + n,
  columns: [{ name: 'c' + n, fields: [field(fieldname)] }],
})
const fieldnames = (tabs) =>
  tabs.flatMap((t) =>
    t.sections.flatMap((s) =>
      s.columns.flatMap((c) => c.fields.map((f) => f.fieldname)),
    ),
  )

function open(initial) {
  const tabs = ref(initial)
  const errors = []
  const w = mount(
    {
      render: () =>
        h(FieldLayoutEditor, {
          modelValue: tabs.value,
          'onUpdate:modelValue': (v) => (tabs.value = v),
          doctype: 'CRM Lead',
        }),
    },
    {
      stubs: { Button, TextInput },
      plugins: [
        { install: (app) => (app.config.errorHandler = (e) => errors.push(e)) },
      ],
    },
  )
  return { tabs, errors, el: w.el }
}

// The menu each section showed on the last render, for one tab's sections.
const latestMenus = (count) => S.menus.slice(-count)
const option = (menu, group, label) =>
  menu[group].options.find((o) => o.label.startsWith(label))

describe('FieldLayoutEditor section menu', () => {
  beforeEach(() => {
    S.menus.length = 0
  })

  it('moves the columns of a removed middle section into the previous one', async () => {
    const { tabs } = open([
      {
        name: 't1',
        label: 'Details',
        sections: [section(0, 'a'), section(1, 'b'), section(2, 'c')],
      },
    ])
    await nextTick()
    const remove = option(latestMenus(3)[1], 0, 'Remove and move columns')
    expect(remove.label).toBe('Remove and move columns to previous section')

    remove.onClick()
    await nextTick()

    expect(fieldnames(tabs.value)).toEqual(['a', 'b', 'c'])
    expect(tabs.value[0].sections.map((s) => s.name)).toEqual(['s0', 's2'])
    expect(tabs.value[0].sections[0].columns.map((c) => c.name)).toEqual([
      'c0',
      'c1',
    ])
  })

  it('offers no section to move into where there is none', async () => {
    open([
      { name: 't1', label: 'Details', sections: [section(0, 'a')] },
      {
        name: 't2',
        label: 'More',
        sections: [section(1, 'b'), section(2, 'c')],
      },
    ])
    await nextTick()
    // Rendered: tab 1's one section, then tab 2's two.
    const [only, first, last] = latestMenus(3)
    expect(option(only, 0, 'Remove and move columns').condition()).toBeFalsy()
    // On the second tab, the first section has nothing before it...
    expect(
      option(first, 1, 'Move Last Column to Previous Section').condition(),
    ).toBeFalsy()
    expect(
      option(first, 1, 'Move Last Column to Next Section').condition(),
    ).toBeTruthy()
    // ...and the last has nothing after it.
    expect(
      option(last, 1, 'Move Last Column to Next Section').condition(),
    ).toBeFalsy()
  })

  it('stops offering to move a column out of a section that has none left', async () => {
    const { tabs, errors } = open([
      {
        name: 't1',
        label: 'Details',
        sections: [section(0, 'a'), section(1, 'b')],
      },
    ])
    await nextTick()
    option(latestMenus(2)[0], 1, 'Move Last Column to Next Section').onClick()
    await nextTick()

    const emptied = latestMenus(2)[0]
    expect(
      option(emptied, 1, 'Move Last Column to Next Section').condition(),
    ).toBeFalsy()
    expect(
      option(emptied, 0, 'Remove and move columns').condition(),
    ).toBeFalsy()
    expect(tabs.value[0].sections[1].columns.map((c) => c.name)).toEqual([
      'c1',
      'c0',
    ])
    expect(errors).toEqual([])
  })
})

describe('FieldLayoutEditor after Reset', () => {
  it('shows the first tab when the reloaded layout has fewer tabs', async () => {
    const { tabs, errors, el } = open([
      { name: 't1', label: 'Details', sections: [section(0, 'a')] },
    ])
    await nextTick()
    el.querySelector('button[data-label="Add Tab"]').click()
    el.querySelector('button[data-label="Add Tab"]').click()
    await nextTick()
    expect(tabs.value).toHaveLength(3)

    // Reset: the modal reloads the saved layout and swaps it in whole.
    tabs.value = [{ name: 't1', label: 'Details', sections: [section(0, 'a')] }]
    await nextTick()

    expect(errors).toEqual([])
    expect(el.textContent).toContain('Details')
  })
})
