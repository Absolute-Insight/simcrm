import { beforeEach, describe, expect, it, vi } from 'vitest'

const callMock = vi.fn()
vi.mock('frappe-ui', () => ({ call: (...args) => callMock(...args) }))

import { createChatStore } from '@/stores/agentChat'

function makeStore(overrides = {}) {
  return createChatStore({
    method: 'crm.agent.api.ask_assistant',
    mapResult: (r) => ({ content: r.answer, sources: r.sources }),
    ...overrides,
  })
}

describe('createChatStore', () => {
  beforeEach(() => callMock.mockClear())

  it('sends the question with prior turns as history and appends the answer', async () => {
    callMock.mockResolvedValue({
      status: 'ok',
      answer: 'Hi',
      sources: [{ name: 'a', title: 'A' }],
    })
    const store = makeStore()
    await store.ask('hello')
    expect(callMock).toHaveBeenCalledWith('crm.agent.api.ask_assistant', {
      question: 'hello',
      history: [],
    })
    expect(store.messages.value).toEqual([
      { role: 'user', content: 'hello' },
      {
        role: 'assistant',
        content: 'Hi',
        sources: [{ name: 'a', title: 'A' }],
      },
    ])

    await store.ask('again')
    // history carries role and content only — never the extras
    expect(callMock.mock.calls[1][1].history).toEqual([
      { role: 'user', content: 'hello' },
      { role: 'assistant', content: 'Hi' },
    ])
  })

  it('ignores blank questions and questions sent while one is pending', async () => {
    const store = makeStore()
    await store.ask('   ')
    expect(callMock).not.toHaveBeenCalled()

    let resolve
    callMock.mockReturnValue(new Promise((r) => (resolve = r)))
    const first = store.ask('one')
    await store.ask('two')
    expect(callMock).toHaveBeenCalledTimes(1)
    resolve({ status: 'ok', answer: 'x' })
    await first
  })

  it('records disabled, empty and unavailable without an answer turn', async () => {
    const store = makeStore()
    callMock.mockResolvedValue({ status: 'disabled', reason: 'analyst_off' })
    await store.ask('q')
    expect(store.failure.value).toBe('disabled')
    expect(store.failureReason.value).toBe('analyst_off')

    callMock.mockResolvedValue({ status: 'empty' })
    await store.ask('q2')
    expect(store.failure.value).toBe('empty')
    expect(store.failureReason.value).toBe('')

    callMock.mockRejectedValueOnce(new Error('boom'))
    await store.ask('q3')
    expect(store.failure.value).toBe('unavailable')

    expect(
      store.messages.value.filter((m) => m.role === 'assistant'),
    ).toHaveLength(0)
  })

  it('retry re-sends the last unanswered question once', async () => {
    const store = makeStore()
    callMock.mockImplementationOnce(() => Promise.reject(new Error('down')))
    await store.ask('q')
    callMock.mockResolvedValue({ status: 'ok', answer: 'ok' })
    await store.retry()
    expect(callMock).toHaveBeenCalledTimes(2)
    expect(store.messages.value.map((m) => m.role)).toEqual([
      'user',
      'assistant',
    ])
    expect(store.failure.value).toBe('')
    // nothing to retry once answered
    await store.retry()
    expect(callMock).toHaveBeenCalledTimes(2)
  })

  it('clear empties the transcript and the failure; toggle flips visibility', async () => {
    const store = makeStore()
    callMock.mockResolvedValue({ status: 'empty' })
    await store.ask('q')
    store.clear()
    expect(store.messages.value).toEqual([])
    expect(store.failure.value).toBe('')
    expect(store.visible.value).toBe(false)
    store.toggle()
    expect(store.visible.value).toBe(true)
  })

  it('caps the history it sends', async () => {
    const store = makeStore({ historyTurns: 2 })
    callMock.mockResolvedValue({ status: 'ok', answer: 'a' })
    await store.ask('1')
    await store.ask('2')
    await store.ask('3')
    expect(callMock.mock.calls[2][1].history).toEqual([
      { role: 'user', content: '2' },
      { role: 'assistant', content: 'a' },
    ])
  })
})
