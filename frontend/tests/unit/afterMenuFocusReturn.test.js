import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { afterMenuFocusReturn } from '@/utils/afterMenuFocusReturn'

describe('afterMenuFocusReturn', () => {
  let menu, item, trigger

  beforeEach(() => {
    vi.useFakeTimers()
    menu = document.createElement('div')
    menu.setAttribute('role', 'menu')
    item = document.createElement('button')
    menu.append(item)
    trigger = document.createElement('button')
    document.body.append(menu, trigger)
  })

  afterEach(() => {
    vi.useRealTimers()
    menu.remove()
    trigger.remove()
  })

  it('waits for focus to leave the menu', () => {
    const run = vi.fn()
    item.focus()
    afterMenuFocusReturn(run)
    expect(run).not.toHaveBeenCalled()
    trigger.focus()
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('ignores focus moving between items of the menu', () => {
    const run = vi.fn()
    const other = document.createElement('button')
    menu.append(other)
    item.focus()
    afterMenuFocusReturn(run)
    other.focus()
    expect(run).not.toHaveBeenCalled()
  })

  it('runs once, and leaves no listener behind', () => {
    const run = vi.fn()
    item.focus()
    afterMenuFocusReturn(run)
    trigger.focus()
    item.focus()
    trigger.focus()
    vi.advanceTimersByTime(5000)
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('does not wait forever if the focus never comes back', () => {
    const run = vi.fn()
    item.focus()
    afterMenuFocusReturn(run)
    vi.advanceTimersByTime(5000)
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('has nothing to wait for when no menu holds focus', () => {
    const run = vi.fn()
    trigger.focus()
    afterMenuFocusReturn(run)
    vi.advanceTimersByTime(0)
    expect(run).toHaveBeenCalledTimes(1)
  })
})
