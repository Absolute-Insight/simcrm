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

  it('drops an answer that lands after Clear', async () => {
    // Clear is live while the model thinks, and a local model takes seconds:
    // the late answer used to appear alone in the emptied panel and then
    // travel as history with the next question.
    const store = makeStore()
    let resolve
    callMock.mockReturnValueOnce(new Promise((r) => (resolve = r)))
    const pending = store.ask('Which deals did Thabo win in September?')
    store.clear()
    expect(store.asking.value).toBe(false) // a new question can go now

    resolve({ status: 'ok', answer: 'Thabo won 3 deals worth R 1.2m.' })
    await pending
    expect(store.messages.value).toEqual([])

    callMock.mockResolvedValueOnce({ status: 'ok', answer: 'ok' })
    await store.ask('How do I log a visit?')
    expect(callMock.mock.calls.at(-1)[1].history).toEqual([])
  })

  it('drops a failure that lands after Clear', async () => {
    const store = makeStore()
    let reject
    callMock.mockReturnValueOnce(new Promise((_, r) => (reject = r)))
    const pending = store.ask('q')
    store.clear()
    reject(new Error('timeout'))
    await pending
    expect(store.failure.value).toBe('')
  })

  it('a question asked after Clear is not cut short by the old one', async () => {
    const store = makeStore()
    let resolveOld, resolveNew
    callMock.mockReturnValueOnce(new Promise((r) => (resolveOld = r)))
    const old = store.ask('old')
    store.clear()
    callMock.mockReturnValueOnce(new Promise((r) => (resolveNew = r)))
    const fresh = store.ask('new')

    resolveOld({ status: 'ok', answer: 'stale' })
    await old
    expect(store.asking.value).toBe(true) // still waiting on the new one

    resolveNew({ status: 'ok', answer: 'fresh' })
    await fresh
    expect(store.messages.value.map((m) => m.content)).toEqual(['new', 'fresh'])
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
