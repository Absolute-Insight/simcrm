import { describe, it, expect } from 'vitest'
import { useConfirmGate } from '../../src/composables/confirmGate.js'

/**
 * The Planner's route guard awaits this gate. A promise that never settles does
 * not surface as a stuck dialog -- the dialog is gone by then -- it surfaces as
 * a page the user cannot navigate away from, with nothing on screen to say why.
 * So every way a dialog can close has to end in an answer.
 */
describe('useConfirmGate', () => {
  it('does not open until asked', () => {
    const gate = useConfirmGate()
    expect(gate.open.value).toBe(false)
  })

  it('opens on ask and resolves true when confirmed', async () => {
    const gate = useConfirmGate()
    const answered = gate.ask()
    expect(gate.open.value).toBe(true)

    gate.answer(true)
    await expect(answered).resolves.toBe(true)
    expect(gate.open.value).toBe(false)
  })

  it('resolves false when declined', async () => {
    const gate = useConfirmGate()
    const answered = gate.ask()
    gate.answer(false)
    await expect(answered).resolves.toBe(false)
    expect(gate.open.value).toBe(false)
  })

  /* Escape, a backdrop click, and ConfirmDialog's own Cancel button all reach
     the gate the same way: the dialog's v-model goes false without any handler
     of ours running. */
  it('resolves false when the dialog closes itself', async () => {
    const gate = useConfirmGate()
    const answered = gate.ask()

    gate.open.value = false

    await expect(answered).resolves.toBe(false)
    expect(gate.open.value).toBe(false)
  })

  /* The close that follows a confirm must not overwrite the answer: v-model
     sees `open` go false and writes it back, which is the same path Escape
     takes. It has to be inert once the question is answered. */
  it('keeps a true answer when the close is echoed back', async () => {
    const gate = useConfirmGate()
    const answered = gate.ask()

    gate.answer(true)
    gate.open.value = false

    await expect(answered).resolves.toBe(true)
  })

  it('asks once for concurrent callers and gives them the same answer', async () => {
    const gate = useConfirmGate()
    const first = gate.ask()
    const second = gate.ask()

    expect(second).toBe(first)

    gate.answer(true)
    expect(await Promise.all([first, second])).toEqual([true, true])
  })

  it('asks again after the previous question is answered', async () => {
    const gate = useConfirmGate()

    const first = gate.ask()
    gate.answer(true)
    await expect(first).resolves.toBe(true)

    const second = gate.ask()
    expect(second).not.toBe(first)
    expect(gate.open.value).toBe(true)

    gate.answer(false)
    await expect(second).resolves.toBe(false)
  })

  /* Answering with no question outstanding is what a stray close event is, and
     it must not throw its way out of a template handler. */
  it('ignores an answer nobody asked for', () => {
    const gate = useConfirmGate()
    expect(() => gate.answer(true)).not.toThrow()
    expect(gate.open.value).toBe(false)
  })
})
