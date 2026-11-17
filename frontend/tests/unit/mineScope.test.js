import { beforeEach, describe, expect, it, vi } from 'vitest'

const { resource } = vi.hoisted(() => ({
  resource: { data: null, error: null },
}))

vi.mock('frappe-ui', () => ({
  createResource: () => resource,
}))

// Node's own localStorage global shadows happy-dom's and is not usable here.
const mem = new Map()
Object.defineProperty(globalThis, 'localStorage', {
  value: {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, String(v)),
  },
  configurable: true,
})

const { useMineScope, MINE, ALL } = await import('@/composables/useMineScope')

const customers = (names, user) => ({ account_owner: user, names })

beforeEach(() => {
  resource.data = null
  resource.error = null
  mem.clear()
})

describe('useMineScope', () => {
  it('waits for the answer before the list loads', () => {
    const mine = useMineScope('t1', customers, 'rep@x')
    expect(mine.ready.value).toBe(false)
  })

  it('starts a rep with customers on Mine, with the filters that mean it', () => {
    resource.data = ['Western Platinum', 'C-LON001G']
    const mine = useMineScope('t2', customers, 'rep@x')
    expect(mine.ready.value).toBe(true)
    expect(mine.available.value).toBe(true)
    expect(mine.scope.value).toBe(MINE)
    expect(mine.filters.value).toEqual({
      account_owner: 'rep@x',
      names: ['Western Platinum', 'C-LON001G'],
    })
  })

  it('has nothing to narrow to for a user who owns no customer', () => {
    resource.data = []
    const mine = useMineScope('t3', customers, 'rep@x')
    expect(mine.available.value).toBe(false)
    expect(mine.scope.value).toBe(ALL)
    expect(mine.filters.value).toEqual({})
  })

  it('remembers All per page, and shows the whole list then', () => {
    resource.data = ['Western Platinum']
    const first = useMineScope('t4', customers, 'rep@x')
    first.scope.value = ALL
    const again = useMineScope('t4', customers, 'rep@x')
    expect(again.scope.value).toBe(ALL)
    expect(again.filters.value).toEqual({})
    // another page keeps its own choice
    expect(useMineScope('t5', customers, 'rep@x').scope.value).toBe(MINE)
  })

  it('shows the whole list when the lookup fails, rather than none', () => {
    resource.error = new Error('offline')
    const mine = useMineScope('t6', customers, 'rep@x')
    expect(mine.ready.value).toBe(true)
    expect(mine.scope.value).toBe(ALL)
  })
})
