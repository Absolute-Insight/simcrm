import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from './mount.js'

vi.mock('frappe-ui', () => ({
  Avatar: defineComponent({
    props: ['label', 'image'],
    setup: (props) => () =>
      h('i', { 'data-label': props.label, 'data-image': props.image }),
  }),
}))
// as the real store: no name means the signed-in user
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    getUser: (name) =>
      name === 'rep@mbp.test'
        ? { full_name: 'A Rep', user_image: '/rep.png' }
        : { full_name: 'The Viewer', user_image: '/viewer.png' },
  }),
}))

const { default: UserAvatar } = await import('@/components/UserAvatar.vue')
const avatar = (props) => mount(UserAvatar, { props }).el.querySelector('i')

describe('UserAvatar', () => {
  it('draws the user it is given', () => {
    const shown = avatar({ user: 'rep@mbp.test' })
    expect(shown.dataset.label).toBe('A Rep')
    expect(shown.dataset.image).toBe('/rep.png')
  })

  it('draws a label for what is not a user, not the signed-in user', () => {
    const shown = avatar({ user: null, label: 'Impala Springs' })
    expect(shown.dataset.label).toBe('Impala Springs')
    expect(shown.dataset.image).toBeUndefined()
  })
})
