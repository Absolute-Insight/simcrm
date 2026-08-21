import { describe, it, expect, vi } from 'vitest'
import { broadcastBus } from '@/composables/useBroadcast'

describe('broadcastBus', () => {
  it('delivers the event detail to the handler', () => {
    const handler = vi.fn()
    broadcastBus.on('ping', handler)
    window.dispatchEvent(new CustomEvent('ping', { detail: { a: 1 } }))
    expect(handler).toHaveBeenCalledWith({ a: 1 })
    broadcastBus.off('ping', handler)
  })

  it('off removes the listener registered by on', () => {
    const handler = vi.fn()
    broadcastBus.on('pong', handler)
    broadcastBus.off('pong', handler)
    window.dispatchEvent(new CustomEvent('pong', { detail: 1 }))
    expect(handler).not.toHaveBeenCalled()
  })

  it('off tolerates a handler that was never registered', () => {
    expect(() => broadcastBus.off('nope', () => {})).not.toThrow()
  })
})
