import { describe, expect, it } from 'vitest'
import { validationErrorMessage } from '@/utils/formScriptErrors'

const FALLBACK = 'This could not be saved.'

describe('validationErrorMessage', () => {
  it("shows the author's own sentence from a plain Error", () => {
    /* The guide's first-listed idiom: `throw new Error(...)`. It used to abort
       the save with nothing on screen. */
    const error = new Error('Provide at least one contact method')
    expect(validationErrorMessage(error, FALLBACK)).toBe(
      'Provide at least one contact method',
    )
  })

  it('stays silent for an error throwError already reported', () => {
    // throwError toasts on its way out, so reporting again would say the same
    // sentence twice in a row.
    const error = new Error('Lead name cannot be empty')
    error.__reported = true
    expect(validationErrorMessage(error, FALLBACK)).toBeNull()
  })

  it('accepts a bare string, since a script may throw one', () => {
    expect(validationErrorMessage('Not allowed', FALLBACK)).toBe('Not allowed')
  })

  it('falls back when the throw carried no message', () => {
    for (const thrown of [new Error(), new Error('   '), {}, null, undefined]) {
      expect(validationErrorMessage(thrown, FALLBACK)).toBe(FALLBACK)
    }
  })

  it('never returns an empty sentence for an unreported error', () => {
    // Silence is the bug being fixed; an empty toast is the same silence.
    for (const thrown of [new Error(''), '', 0, false, {}]) {
      const message = validationErrorMessage(thrown, FALLBACK)
      expect(message).toBeTruthy()
    }
  })

  it('trims whitespace an author left around the message', () => {
    expect(validationErrorMessage(new Error('  Too low  '), FALLBACK)).toBe(
      'Too low',
    )
  })
})
